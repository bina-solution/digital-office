#!/usr/bin/env bash
# follow.sh — an office FOLLOWS dgo-stable by itself (r030-201).
#
#     ./bbox follow [--dry-run]    one cycle: what the host timer runs (--dry-run says what it would do)
#     ./bbox follow status         what is declared, where this office stands, the last cycle
#     ./bbox follow install        install or remove the host timer from the declaration (`bbox run` does this)
#     ./bbox follow clear          after a session repaired a stopped take by hand: forget it, follow again
#
# WHY. Nothing kept an office current: it took dgo-stable only when a person or a session merged it by hand. The
# HP drifted 761 commits in ten days, and every door that would have let another office update it was itself new
# code the HP did not have — so the only way left was the owner, at the machine (rep-local-261102-201500).
#
# THE DECLARATION is .env: DGO_FOLLOW=dgo-stable (empty: this office does not follow). DGO_BRANCH is the office's
# own branch, the only one ever written (the branch rule, AGENTS.md). DGO_FOLLOW_GATES names the workflow whose
# success makes a commit takeable (default gates-hosted.yml). The MacBook leaves DGO_FOLLOW empty: live sessions
# commit in its checkout, and a merge under them is the one thing this must never do.
#
# ONE CYCLE (the timer's, every 30 minutes) makes at most ONE change, and every change is a TAKE:
#   1. One at a time (flock, held by flock(1) itself so nothing the cycle starts inherits it); never beside another
#      heavy job (the bbox heavy slot), on a loaded host, or while an app says it is in use (its own hooks/busy: Meet,
#      a call in progress); only on DGO_BRANCH, with no git command in flight.
#   2. A take an earlier cycle did not finish is settled first (TAKING in the state): rolled back if it was never
#      verified, and the cycle stops — sticky — when the checkout moved on top of it. Nothing is ever called current
#      while one is open.
#   3. The office's own branch, if origin is ahead of the checkout (pushed from elsewhere), is a take of its own.
#   4. Otherwise the target is the newest first-parent commit of origin/DGO_FOLLOW whose gates run SUCCEEDED (GitHub's
#      API, with the checkout's own git credential, in memory and handed to curl on stdin, never in argv).
#   A TAKE: refused before anything moves when the index holds staged changes, a modified file is one the target
#   changes (renames counted as both paths), or a file the target adds is already on disk untracked. platform.state.yaml
#   is the office's own state (the console and the link write it): committed on the office branch first, when the
#   target touches it — but a dgo-stable take that would change which apps it DECLARES enabled (another office's
#   decision, merged into dgo-stable) is undone before anything runs. Then `bbox run`, and every service that was
#   running and healthy before must be running and healthy after (one that vanished counts, unless the take retired it
#   from the compiled model; services that cannot be read count). Healthy, and
#   HEAD still the merge → push (never forced). Not → `git reset --keep` to the commit before (never pushed, so no
#   published history changes), `bbox run` again, and the target is not taken again until a newer one is green.
# The owner hears only what failed: ONE row in the notice centre (source `follow`), written once per distinct text,
# updated in place, and closed with «back to normal» by the next good take or current cycle.
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
OFFICE="$(read_env DGO_OFFICE_ID)"; OFFICE="${OFFICE:-${DN}}"
STATE_DIR="${REPO_ROOT}/data/follow"
STATE="${STATE_DIR}/state"
SETTLE="${DGO_FOLLOW_SETTLE:-600}"      # seconds a service may still be "starting" after `bbox run`
UNIT=dgo-follow
DRY=0
export GIT_TERMINAL_PROMPT=0            # a timer has no terminal: a missing credential fails, never waits
git() { command git -c core.quotePath=false -C "${REPO_ROOT}" "$@"; }   # paths as they are on disk
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
post_notice() {   # level title body
  if [ -n "${DGO_FOLLOW_NOTIFY_CMD:-}" ]; then "${DGO_FOLLOW_NOTIFY_CMD}" "$@"; return; fi
  local cid
  cid="$("${REPO_ROOT}/scripts/dc" ps -q notifications 2>/dev/null | head -1)"
  [ -n "${cid}" ] || { say "the notice centre is not running here — not told: $2"; return 1; }
  python3 -c 'import json, sys
print(json.dumps({"source": "follow", "source_id": "follow:" + sys.argv[1], "level": sys.argv[2],
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
  post_notice info "המשרד מעודכן שוב — ${OFFICE}" "back to normal: $1" && st_set NOTICE ""
}

# ── the gates ─────────────────────────────────────────────────────────────────────────────────────
green_shas() {   # the head commits of DGO_FOLLOW whose ${GATES} run succeeded, one per line
  if [ -n "${DGO_FOLLOW_GREEN_CMD:-}" ]; then "${DGO_FOLLOW_GREEN_CMD}"; return; fi
  local url slug tok
  url="$(git remote get-url origin 2>/dev/null)" || return 1
  # never print the URL: it may carry a credential
  case "${url}" in *github.com[:/]*) ;; *) say "origin is not on GitHub — its gates cannot be read"; return 1 ;; esac
  slug="$(printf '%s' "${url}" | sed -E 's#\.git$##; s#^.*github\.com[:/]##')"
  tok="$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill 2>/dev/null | sed -n 's/^password=//p')"
  { [ -z "${tok}" ] || printf 'header = "Authorization: Bearer %s"\n' "${tok}"; } \
    | curl -sf --max-time 30 -K - -H 'Accept: application/vnd.github+json' \
        "https://api.github.com/repos/${slug}/actions/workflows/${GATES}/runs?branch=${FOLLOW}&status=success&per_page=100" \
    | python3 -c 'import json, sys
for r in json.load(sys.stdin).get("workflow_runs", []):
    print(r["head_sha"])'
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
lost() {   # before after → every service that was good before and is not good now ("<name> gone" when it vanished)
  # A service gone from the running office AND from the compiled model, that the take itself retired, is a release.
  # When the model cannot be read, every vanished service counts.
  local n line model
  model="$(model_services)" || model=""
  printf '%s\n' "$1" | good_names | while read -r n; do
    line="$(printf '%s\n' "$2" | awk -v n="${n}" '$1 == n')"
    if [ -z "${line}" ]; then
      [ -n "${model}" ] && ! grep -qxF -- "${n}" <<<"${model}" && retired "${n}" && continue
      echo "${n} gone"
    elif ! grep -qxF -- "${n}" <<<"$(good_names <<<"${line}")"; then echo "${line}"; fi
  done
}
# The apps platform.state.yaml at <rev> DECLARES enabled, by reconcile.py's own rule (disposition(): `state:` when it is
# one of its words, else `enabled: true|false`, else disabled) — the office's own decisions, not the resolved set (a
# release that adds a base app changes that for every office, and is exactly what following is for). Fails when the
# file cannot be read or parsed.
declared_apps() {
  git show "$1:platform.state.yaml" 2>/dev/null | python3 -c 'import sys, yaml
apps = (yaml.safe_load(sys.stdin) or {}).get("apps") or {}
for aid, e in sorted(apps.items()):
    e = e if isinstance(e, dict) else {}
    st = str(e.get("state") or "").strip().lower()
    if st not in ("enabled", "disabled", "archived"):
        st = ("enabled" if e.get("enabled") else "disabled") if "enabled" in e else "disabled"
    if st == "enabled":
        print(aid)' 2>/dev/null
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
office_run() {   # bbox run, logged; the exit code is the run's
  # A rollback goes back ON PURPOSE: the deploy ledger (scripts/lib.sh, deploy_ledger_gate) refuses a bring-up that
  # drops what runs here unless the command says so — without it the checkout was back at the commit before while the
  # containers stayed on the failed take, and the owner was told the office was back (the second reader, r030-205).
  local back=0; [ "$1" = rollback ] && back=1
  if [ -n "${DGO_FOLLOW_RUN_CMD:-}" ]; then BBOX_ALLOW_ROLLBACK="${back}" "${DGO_FOLLOW_RUN_CMD}" "$1"; return; fi
  BBOX_ALLOW_ROLLBACK="${back}" "${REPO_ROOT}/bbox" run > "${STATE_DIR}/run-$(date -u '+%Y%m%dT%H%M%S')-$1.log" 2>&1
}

# ── the host timer ────────────────────────────────────────────────────────────────────────────────
install_timer() {
  local sudo="" dir=/etc/systemd/system owner svc tim
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
  if [ -z "${FOLLOW}" ]; then
    [ -e "${dir}/${UNIT}.timer" ] || return 0
    ${sudo} systemctl disable --now "${UNIT}.timer" >/dev/null 2>&1 || true
    ${sudo} rm -f "${dir}/${UNIT}.timer" "${dir}/${UNIT}.service" && ${sudo} systemctl daemon-reload
    say "DGO_FOLLOW is empty — the follow timer is removed"
    return 0
  fi
  owner="$(stat -c %U "${REPO_ROOT}" 2>/dev/null)" || owner=root
  # TimeoutStartSec above the heavy slot's own 3-hour wait, so a run that queued behind a build is not killed mid-take
  svc="$(printf '%s\n' '[Unit]' \
    "Description=DGO follow: take ${FOLLOW} into ${BRANCH} when its gates are green (scripts/follow.sh)" \
    'After=docker.service network-online.target' 'Wants=network-online.target' '' \
    '[Service]' 'Type=oneshot' "User=${owner}" "WorkingDirectory=${REPO_ROOT}" \
    "ExecStart=\"${REPO_ROOT}/bbox\" follow" 'Nice=10' 'TimeoutStartSec=6h')"
  tim="$(printf '%s\n' '[Unit]' "Description=DGO follow, every 30 minutes (scripts/follow.sh)" '' \
    '[Timer]' 'OnBootSec=15min' 'OnUnitInactiveSec=30min' 'RandomizedDelaySec=5min' '' \
    '[Install]' 'WantedBy=timers.target')"
  if [ "$(cat "${dir}/${UNIT}.service" 2>/dev/null)" != "${svc}" ] || [ "$(cat "${dir}/${UNIT}.timer" 2>/dev/null)" != "${tim}" ]; then
    printf '%s\n' "${svc}" | ${sudo} tee "${dir}/${UNIT}.service" >/dev/null \
      && printf '%s\n' "${tim}" | ${sudo} tee "${dir}/${UNIT}.timer" >/dev/null \
      && ${sudo} systemctl daemon-reload || { say "${cy}could not write the follow timer into ${dir}${c0}"; return 1; }
    say "follow timer installed: ${FOLLOW} → ${BRANCH}, every 30 minutes, as ${owner}"
  fi
  ${sudo} systemctl is-enabled --quiet "${UNIT}.timer" 2>/dev/null && ${sudo} systemctl is-active --quiet "${UNIT}.timer" \
    || ${sudo} systemctl enable --now "${UNIT}.timer" >/dev/null 2>&1 \
    || { say "${cy}could not enable ${UNIT}.timer${c0}"; return 1; }
}

status() {
  local behind="?" timer="not installed"
  say "declared: DGO_FOLLOW=${FOLLOW:-<empty: not following>}  DGO_BRANCH=${BRANCH:-<empty>}  gates: ${GATES}"
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
  [ -z "$(st_get TAKING)" ] || say "a take is open: $(st_get TAKING) (merged: $(st_get MERGED))"
  [ -z "$(st_get FAILED_TARGET)" ] || say "not taken again until a newer one is green: $(short "$(st_get FAILED_TARGET)") ($(st_get FAILED_AT))"
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
rollback() {   # prev merged target why — back to the commit before the take, which was never pushed
  local prev="$1" merged="$2" tgt="$3" why="$4" rc=0 still
  st_set WHY "${why}"              # a refused rollback is retried by the next cycle, and says the same
  if [ "$(git rev-parse HEAD)" != "${merged}" ]; then moved_on_top "${tgt}"; return 1; fi
  if ! git reset -q --keep "${prev}" 2>/dev/null; then
    tell "עדכון נכשל ולא חזר אחורה — ${OFFICE}" "Taking $(short "${tgt}") into ${BRANCH} left the office unhealthy (${why}), and going back to $(short "${prev}") was refused by git (local changes in the files it moves). Each cycle tries again; a session can look at \`git status\`."
    finish failed "$(short "${tgt}") unhealthy, and the rollback was refused"; return 1
  fi
  st_set FAILED_TARGET "${tgt}" FAILED_AT "$(date -u '+%F %T UTC')"
  office_run rollback || rc=$?
  TAKE_PREV="" TAKE_MERGED=""   # back on prev: nothing the take did is "retired" any more
  still="$(settle)" && still="$(lost "$(st_get BEFORE | tr ';' '\n')" "${still}")" || still="the services cannot be read"
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
  base="$(git merge-base HEAD "$2")" || return 1
  for c in $(git --literal-pathspecs log --format=%H -n 500 "${base}..$2" -- "$1"); do
    [ "$(git --literal-pathspecs ls-tree "${c}" -- "$1" | cut -f1 | awk '{print $1, $3}')" = "${ours}" ] && return 0
  done
  return 1
}
settle_carried() {   # target conflicts(newline list) → 0 when every conflict was carried content, resolved and committed
  local tgt="$1" p
  while IFS= read -r p; do [ -z "${p}" ] || carried "${p}" "${tgt}" || return 1; done <<<"$2"
  while IFS= read -r p; do
    [ -n "${p}" ] || continue
    if git cat-file -e "${tgt}:${p}" 2>/dev/null; then git --literal-pathspecs checkout -q "${tgt}" -- "${p}" || return 1
    else git --literal-pathspecs rm -q -- "${p}" || return 1; fi   # DGO_FOLLOW removed it; the office's copy was carried
  done <<<"$2"
  git commit -q -m "follow: take ${FOLLOW} $(short "${tgt}") into ${BRANCH} (${GATES} green); content ${FOLLOW} itself carried, its versions taken: $(tr '\n' ' ' <<<"$2")" \
    || return 1
  say "the take's conflicts were content ${FOLLOW} itself had carried: $(tr '\n' ' ' <<<"$2")— its versions taken"
}

take() {   # ref what — merge ref into BRANCH, run, verify, push or roll back
  local tgt what="$2" changed dirty overlap rest added present apps_before apps_after before after bad prev merged out rc conflicts
  tgt="$(git rev-parse "$1")" || return 1
  if [ "$(st_get FAILED_TARGET)" = "${tgt}" ]; then
    finish waiting "${what} $(short "${tgt}") failed at $(st_get FAILED_AT); waiting for a newer one"; return 0
  fi
  # refused before anything moves: these are the office's side, never the target's fault (no FAILED_TARGET)
  if ! git diff --cached --quiet; then
    tell "לא ניתן לעדכן: שינויים מוכנים לקומיט — ${OFFICE}" "The index of ${BRANCH} holds staged changes ($(git diff --cached --name-only | head -5 | tr '\n' ' ')); a merge would refuse. Commit or unstage them; nothing was merged."
    finish blocked "staged changes in the checkout"; return 1
  fi
  changed="$(git diff --name-only --no-renames "HEAD...${tgt}")"
  dirty="$(git diff --name-only --no-renames HEAD)"
  overlap="$(printf '%s\n' "${dirty}" | grep -Fx -f <(printf '%s\n' "${changed}" | sed '/^$/d') || true)"
  rest="$(printf '%s\n' "${overlap}" | grep -vFx platform.state.yaml | sed '/^$/d' || true)"
  if [ -n "${rest}" ]; then
    tell "לא ניתן לעדכן: שינויים מקומיים בקבצים שהעדכון משנה — ${OFFICE}" "Uncommitted changes here in: ${rest//$'\n'/ } — ${what} $(short "${tgt}") changes them too. Commit or drop them on ${BRANCH}; nothing was merged."
    finish blocked "local changes in ${rest//$'\n'/ }"; return 1
  fi
  added="$(git diff --name-only --no-renames --diff-filter=A "HEAD...${tgt}")"
  # on disk and NOT tracked here (a file the office already has through a cherry-pick merges cleanly)
  present="$(printf '%s\n' "${added}" | sed '/^$/d' | while read -r f; do
    git cat-file -e "HEAD:${f}" 2>/dev/null && continue
    [ -e "${REPO_ROOT}/${f}" ] || [ -L "${REPO_ROOT}/${f}" ] && printf '%s ' "${f}"; done)"
  if [ -n "${present}" ]; then
    tell "לא ניתן לעדכן: קבצים מקומיים במקום שהעדכון מוסיף — ${OFFICE}" "${what} $(short "${tgt}") adds ${present}which already exist here, untracked or ignored. Move them away; nothing was merged."
    finish blocked "files already where the take adds them: ${present}"; return 1
  fi
  # an app in use right now (a meeting) is not recreated under its people: the next cycle tries again
  local busy; busy="$(busy_apps)"
  if [ -n "${busy}" ]; then finish skipped "busy — ${busy//$'\n'/; }"; return 0; fi
  if [ "${DRY}" = 1 ]; then
    say "would take ${what} $(short "${tgt}") into ${BRANCH} at $(short HEAD): $(git rev-list --count "HEAD..${tgt}") commit(s), $(printf '%s\n' "${changed}" | sed '/^$/d' | wc -l | tr -d ' ') file(s)"
    grep -qFx platform.state.yaml <<<"${overlap}" && say "would first commit this office's own platform.state.yaml on ${BRANCH}"
    say "then: bbox run, every healthy service compared ($(services | good_names | wc -l | tr -d ' ') healthy now), push or roll back"
    return 0
  fi
  before="$(settle)" || { finish skipped "the services cannot be read before the take"; return 0; }
  # asked again: the baseline may have waited minutes, and a meeting may have begun in them — seconds before the merge
  busy="$(busy_apps)"
  if [ -n "${busy}" ]; then finish skipped "busy — ${busy//$'\n'/; }"; return 0; fi
  export GIT_AUTHOR_NAME="dgo-follow (${OFFICE})" GIT_COMMITTER_NAME="dgo-follow (${OFFICE})"
  export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-$(git config user.email || echo "follow@${OFFICE}.invalid")}"
  export GIT_COMMITTER_EMAIL="${GIT_AUTHOR_EMAIL}"
  if grep -qFx platform.state.yaml <<<"${overlap}"; then
    git commit -q -m "follow: ${OFFICE}'s own platform state, before taking ${what} $(short "${tgt}")" \
      -- platform.state.yaml || { finish blocked "could not commit platform.state.yaml"; return 1; }
  fi
  prev="$(git rev-parse HEAD)"
  # recorded BEFORE the merge: a cycle killed from here on is settled by the next one (recover)
  st_set TAKING "${prev} ${tgt}" MERGED "" BEFORE "$(printf '%s' "${before}" | tr '\n' ';')"
  if ! out="$(git merge -q --no-edit -m "follow: take ${what} $(short "${tgt}") into ${BRANCH} (${GATES} green)" "${tgt}" 2>&1)" \
     && ! { conflicts="$(git diff --name-only --diff-filter=U)"; [ -n "${conflicts}" ] && [ "${what}" = "${FOLLOW}" ] \
            && settle_carried "${tgt}" "${conflicts}"; }; then
    local files gd; files="$(git diff --name-only --diff-filter=U | tr '\n' ' ')"; gd="$(git rev-parse --absolute-git-dir)"
    # every path resolved and then the commit failed: still the conflicts, not "refused before it started"
    [ -n "${files}" ] || files="$(tr '\n' ' ' <<<"${conflicts:-}" | sed 's/^ *$//')"
    if [ -e "${gd}/MERGE_HEAD" ] && ! git merge --abort 2>/dev/null; then
      tell "עדכון נתקע באמצע מיזוג — ${OFFICE}" "Merging ${what} $(short "${tgt}") into ${BRANCH} conflicted${files:+ in ${files}}, and \`git merge --abort\` failed: the checkout is mid-merge. A session must finish or abort it, then run \`bbox follow clear\`."
      finish blocked "mid-merge, abort failed"; return 1
    fi
    st_set TAKING "" MERGED "" BEFORE ""
    if [ -n "${files}" ]; then
      st_set FAILED_TARGET "${tgt}" FAILED_AT "$(date -u '+%F %T UTC')"
      tell "לא ניתן לעדכן: התנגשות במיזוג — ${OFFICE}" "Merging ${what} $(short "${tgt}") into ${BRANCH} conflicts in ${files}— aborted; ${BRANCH} is unchanged at $(short HEAD). A session must merge it by hand."
      finish failed "merge of $(short "${tgt}") conflicts in ${files}"; return 1
    fi
    tell "לא ניתן לעדכן: git סירב למיזוג — ${OFFICE}" "Merging ${what} $(short "${tgt}") into ${BRANCH} was refused before it started: $(printf '%s' "${out}" | head -3 | tr '\n' ' ') Nothing was merged."
    finish blocked "merge refused: $(printf '%s' "${out}" | head -1)"; return 1
  fi
  merged="$(git rev-parse HEAD)"; st_set MERGED "${merged}"
  # Another office's state, merged into dgo-stable, must not decide which apps run HERE. (The office's own branch, taken
  # from origin, IS this office's decision: not checked.)
  TAKE_PREV="${prev}" TAKE_MERGED="${merged}" TAKE_APPS_MOVED=0
  if ! apps_before="$(declared_apps "${prev}")" || ! apps_after="$(declared_apps "${merged}")"; then
    git reset -q --keep "${prev}" 2>/dev/null || { finish failed "the declared apps cannot be read, and undoing the merge was refused"; return 1; }
    st_set TAKING "" MERGED "" BEFORE ""
    if [ -n "$(declared_apps "${prev}")" ]; then   # ours reads, the merged one does not: the target's fault, not retried
      st_set FAILED_TARGET "${tgt}" FAILED_AT "$(date -u '+%F %T UTC')"
      tell "לא ניתן לעדכן: platform.state.yaml שבור אחרי המיזוג — ${OFFICE}" "Merged with ${what} $(short "${tgt}"), platform.state.yaml cannot be parsed. Nothing ran; ${BRANCH} is back at $(short "${prev}"). A session must merge it by hand."
      finish failed "platform.state.yaml unreadable after merging $(short "${tgt}")"; return 1
    fi
    finish skipped "the apps platform.state.yaml declares cannot be read (python3 + yaml) — nothing ran"; return 0
  fi
  [ "${apps_after}" = "${apps_before}" ] || TAKE_APPS_MOVED=1
  if [ "${what}" = "${FOLLOW}" ] && [ "${TAKE_APPS_MOVED}" = 1 ]; then
    local plus minus
    plus="$(comm -13 <(printf '%s\n' "${apps_before}") <(printf '%s\n' "${apps_after}") | tr '\n' ' ')"
    minus="$(comm -23 <(printf '%s\n' "${apps_before}") <(printf '%s\n' "${apps_after}") | tr '\n' ' ')"
    git reset -q --keep "${prev}" 2>/dev/null || { finish failed "the apps would change, and undoing the merge was refused"; return 1; }
    st_set TAKING "" MERGED "" BEFORE "" FAILED_TARGET "${tgt}" FAILED_AT "$(date -u '+%F %T UTC')"
    tell "לא ניתן לעדכן: העדכון משנה אילו אפליקציות רצות כאן — ${OFFICE}" "${what} $(short "${tgt}") would change which apps this office runs (${plus:+on: ${plus}}${minus:+off: ${minus}}). That is this office's decision, not a merge's: nothing ran, ${BRANCH} is back at $(short "${prev}"). A session must take it by hand."
    finish blocked "the take would change the enabled apps (${plus:+on: ${plus}}${minus:+off: ${minus}})"; return 1
  fi
  say "took ${what} $(short "${tgt}") into ${BRANCH} — bringing the office up on it"
  rc=0; office_run take || rc=$?
  if after="$(settle)"; then bad="$(lost "${before}" "${after}")"; else bad="the services cannot be read"; fi
  [ "${rc}" = 0 ] || bad="${bad:+${bad}$'\n'}bbox run exited ${rc}"
  if [ -n "${bad}" ]; then rollback "${prev}" "${merged}" "${tgt}" "${bad//$'\n'/, }"; return 1; fi
  if [ "$(git rev-parse HEAD)" != "${merged}" ]; then moved_on_top "${tgt}"; return 1; fi
  # the merge itself, not HEAD: a commit landing between the check above and the push is never pushed unchecked
  if git push -q origin "${merged}:refs/heads/${BRANCH}" 2>/dev/null; then
    st_set TAKING "" MERGED "" BEFORE "" FAILED_TARGET "" FAILED_AT "" PUSH_PENDING ""
    finish took "${what} $(short "${tgt}") into ${BRANCH} at $(short HEAD), healthy, pushed"
    all_clear "${what} $(short "${tgt}") taken"
  else
    st_set TAKING "" MERGED "" BEFORE "" FAILED_TARGET "" FAILED_AT "" PUSH_PENDING "${merged}"
    finish took "${what} $(short "${tgt}") into ${BRANCH}, healthy — the push was refused, the next cycle pushes again"
    tell "המשרד עודכן אבל הענף לא נדחף — ${OFFICE}" "${BRANCH} took ${what} $(short "${tgt}") and is healthy, but pushing it to origin was refused; the next cycle pushes again."
  fi
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
    # pushed by an earlier cycle (only a verified take is ever pushed) — unless that take had already failed
    if [ -z "$(st_get WHY)" ] && [ "$(git rev-parse -q --verify "refs/remotes/origin/${BRANCH}")" = "${merged}" ]; then
      st_set TAKING "" MERGED "" BEFORE "" FAILED_TARGET "" FAILED_AT ""   # verified and pushed; only the bookkeeping was lost
      finish took "$(short "${tgt}") into ${BRANCH} (pushed by an earlier cycle)"; return 1
    fi
    local why; why="$(st_get WHY)"
    rollback "${prev}" "${merged}" "${tgt}" "${why:-the cycle that took it was stopped before its health check finished}"
    return 1
  fi
  if [ "${head}" = "${prev}" ]; then
    if [ -n "${merged}" ]; then   # rolled back, then stopped before the run: run it, so the office matches its files
      local why rc=0; why="$(st_get WHY)"
      st_set FAILED_TARGET "${tgt}" FAILED_AT "$(date -u '+%F %T UTC')"
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

# ── one cycle ─────────────────────────────────────────────────────────────────────────────────────
cycle() {
  local cpus load gd green target
  [ -n "${FOLLOW}" ] || { say "DGO_FOLLOW is empty — this office does not follow"; return 0; }
  [ -n "${BRANCH}" ] || { tell "לא ניתן לעקוב: DGO_BRANCH ריק — ${OFFICE}" "DGO_FOLLOW=${FOLLOW} is declared, but the office's own branch (DGO_BRANCH) is not: nothing is merged without it."; return 1; }
  mkdir -p "${REPO_ROOT}/data/.locks" "${STATE_DIR}" || return 1
  if [ "$(heavy_slot_status)" != free ]; then finish skipped "a heavy job holds the slot: $(heavy_slot_status)"; return 0; fi
  cpus="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"
  load="$(cut -d' ' -f1 /proc/loadavg 2>/dev/null || echo 0)"
  if awk -v l="${load}" -v c="${cpus}" -v m="${DGO_FOLLOW_MAX_LOAD:-}" 'BEGIN {exit !(l > (m == "" ? c : m))}'; then
    finish skipped "load ${load} on ${cpus} CPU(s)"; return 0
  fi
  [ "$(git rev-parse --abbrev-ref HEAD)" = "${BRANCH}" ] \
    || { tell "לא ניתן לעקוב: המשרד לא על הענף שלו — ${OFFICE}" "The checkout is on $(git rev-parse --abbrev-ref HEAD), not ${BRANCH} (DGO_BRANCH). Nothing was merged."; finish blocked "not on ${BRANCH}"; return 1; }
  gd="$(git rev-parse --absolute-git-dir)"
  # a merge OUR open take left mid-way (the cycle killed between its conflicted merge and the carried commit) is ours to
  # abort, so recover() can settle the take; any other merge in flight is someone else's
  if [ "${DRY}" != 1 ] && [ -e "${gd}/MERGE_HEAD" ] && [ -n "$(st_get TAKING)" ] \
     && [ "$(head -1 "${gd}/MERGE_HEAD")" = "$(st_get TAKING | cut -d' ' -f2)" ]; then
    git merge --abort 2>/dev/null && say "aborted the merge an earlier cycle left mid-way (its open take)"
  fi
  if [ -e "${gd}/MERGE_HEAD" ] || [ -d "${gd}/rebase-merge" ] || [ -d "${gd}/rebase-apply" ] || [ -e "${gd}/index.lock" ]; then
    finish skipped "a merge, rebase or git command is in flight in the checkout"; return 0
  fi
  git fetch -q origin "+refs/heads/${FOLLOW}:refs/remotes/origin/${FOLLOW}" 2>/dev/null \
    || { finish skipped "fetch of ${FOLLOW} failed"; return 0; }
  git fetch -q origin "+refs/heads/${BRANCH}:refs/remotes/origin/${BRANCH}" 2>/dev/null || true
  [ "${DRY}" = 1 ] || recover || return 0

  # the office's own branch, pushed from elsewhere: a take of its own
  if git rev-parse -q --verify "refs/remotes/origin/${BRANCH}" >/dev/null && ! git merge-base --is-ancestor "origin/${BRANCH}" HEAD; then
    if git merge-base --is-ancestor HEAD "origin/${BRANCH}"; then take "origin/${BRANCH}" "origin/${BRANCH}"; return; fi
    tell "לא ניתן לעקוב: הענף של המשרד התפצל — ${OFFICE}" "${BRANCH} here and origin/${BRANCH} have each moved since they last met. A session must join them; nothing was merged."
    finish blocked "${BRANCH} diverged from origin/${BRANCH}"; return 1
  fi

  green="$(green_shas)" || green=""
  [ -n "${green}" ] || { finish skipped "no green ${GATES} run on ${FOLLOW} could be read"; return 0; }
  target="$(git rev-list --first-parent -n 300 "origin/${FOLLOW}" | grep -Fx -f <(printf '%s\n' "${green}") | head -1)"
  [ -n "${target}" ] || { finish skipped "none of the last 300 commits of ${FOLLOW} has a green ${GATES} run"; return 0; }
  if git merge-base --is-ancestor "${target}" HEAD; then
    # a verified take whose push was refused: that merge is pushed, never HEAD (a session may have added to it since)
    local pending; pending="$(st_get PUSH_PENDING)"
    if [ -n "${pending}" ] && [ "${DRY}" != 1 ] && git merge-base --is-ancestor "${pending}" HEAD; then
      git push -q origin "${pending}:refs/heads/${BRANCH}" 2>/dev/null && st_set PUSH_PENDING ""
    fi
    finish current "${FOLLOW} green at $(short "${target}") is in ${BRANCH}"
    [ "${DRY}" = 1 ] || [ -n "$(st_get PUSH_PENDING)" ] \
      || { st_set FAILED_TARGET "" FAILED_AT ""; all_clear "${FOLLOW} $(short "${target}") is in ${BRANCH}"; }
    return 0
  fi
  take "${target}" "${FOLLOW}"
}

case "${1:-}" in
  ""|--dry-run)
    [ "${1:-}" = --dry-run ] && DRY=1
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
    st_set TAKING "" MERGED "" BEFORE "" WHY "" FAILED_TARGET "" FAILED_AT ""
    say "follow: the open take and the failed target are forgotten — the next cycle follows ${FOLLOW:-<nothing>} again" ;;
  -h|--help) sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
  *) die "usage: bbox follow [--dry-run] | status | install | clear" ;;
esac
