#!/usr/bin/env bash
# follow.sh — an office FOLLOWS dgo-stable by itself (r030-201).
#
#     ./bbox follow [--dry-run]    one cycle: what the host timer runs (--dry-run says what it would do)
#     ./bbox follow heal           only the heal a cycle starts with: what the boot timer runs, 3 and 8 minutes in
#     ./bbox follow status        what is declared, where this office stands, the last cycle
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
# commit in its checkout, and a merge under them is the one thing this must never do. An office with no GitHub
# credential of its own (the HP) declares DGO_FOLLOW_VIA=<a linked office> and DGO_FOLLOW_VIA_PATH (its git proxy's
# path for the repository, /git/gh/<account>/<owner>/<repo>.git): each cycle then fetches and pushes through that
# office's git app, at the address `bbox remote` gives NOW — a port written into a remote goes stale (the HP's
# macbook-git pointed at 9004 after the Mac's door moved to 9005).
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
#      API, with the checkout's own git credential (in memory, handed to curl on stdin, never in argv); where that
#      cannot be read, the ref refs/green/DGO_FOLLOW that gates-hosted moves forward on every green run (git data, so
#      any path that brings the code brings it).
#   A TAKE: refused before anything moves when the index holds staged changes, a modified file is one the target
#   changes (renames counted as both paths), or a file the target adds is already on disk untracked. platform.state.yaml
#   is the office's own state (the console and the link write it): committed on the office branch first, when the
#   target touches it — but a dgo-stable take that would change which apps it DECLARES enabled (another office's
#   decision, merged into dgo-stable) is undone before anything runs. Then `bbox run`, and every service that was
#   running and healthy before must be running and healthy after (one that vanished counts, unless the take retired it
#   from the compiled model; services that cannot be read count). Healthy, and
#   HEAD still the merge → push (never forced). Not → `git reset --keep` to the commit before (never pushed, so no
#   published history changes), `bbox run` again, and the target is not taken again until a newer one is green.
# The owner hears what failed: ONE row in the notice centre (source `follow`), written once per distinct text,
# updated in place, and closed with «back to normal» by the next good take or current cycle. And a good take of
# dgo-stable, once, in a row of its own (told_took) — with a row open, its «back to normal» says the take instead.
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
VIA="$(read_env DGO_FOLLOW_VIA)"
VIA_PATH="$(read_env DGO_FOLLOW_VIA_PATH)"
# "A loaded host" is the 1-minute load above this, default the CPU count. An office that runs its agents' sessions
# all day (the HP: 8 of them, DGO-1299) sits above its CPU count while it works, and never took a green dgo-stable
# (skipped at 8–20 on 6 CPUs, 2026-11-03). So the office declares its own ceiling in .env; the environment still wins.
MAX_LOAD="${DGO_FOLLOW_MAX_LOAD:-$(read_env_value DGO_FOLLOW_MAX_LOAD)}"
# A number or nothing: awk compares anything else as text, and "16" quoted skipped every cycle while abc never did.
case "${MAX_LOAD}" in ''|*[!0-9.]*|*.*.*) [ -z "${MAX_LOAD}" ] || warn "DGO_FOLLOW_MAX_LOAD=${MAX_LOAD} is not a number — the CPU count applies"; MAX_LOAD= ;; esac
SRC=origin                              # where a cycle fetches and pushes: origin, or the URL resolve_src() makes
OFFICE="$(read_env DGO_OFFICE_ID)"; OFFICE="${OFFICE:-${DN}}"
STATE_DIR="${REPO_ROOT}/data/follow"
STATE="${STATE_DIR}/state"
SETTLE="${DGO_FOLLOW_SETTLE:-600}"      # seconds a service may still be "starting" after `bbox run`
# seconds a file changed here must be untouched before it is LEFT WORK (take: kept in a commit, or unstaged)
KEEP_AFTER="${DGO_FOLLOW_KEEP_AFTER:-21600}"
UNIT=dgo-follow
DRY=0
HEAL=0                                  # `bbox follow heal`: office_heal, and nothing after it
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
resolve_src() {   # SRC = origin, or DGO_FOLLOW_VIA's git proxy at the address its link publishes NOW; fails, said
  SRC=origin
  [ -n "${VIA}" ] || return 0
  [ -n "${VIA_PATH}" ] \
    || { say "DGO_FOLLOW_VIA=${VIA} is declared without DGO_FOLLOW_VIA_PATH (/git/gh/<account>/<owner>/<repo>.git)"; return 1; }
  local port
  # the DOOR the link publishes for it (registry.link_port), which is what `bbox remote` itself calls — not the app's
  # own port, which only the serving office's network answers on (that one is only the last resort, for a record the
  # compiler has not rendered yet: then the fetch fails and the cycle says so)
  port="$("${DGO_FOLLOW_BBOX:-${REPO_ROOT}/bbox}" remote "${VIA}" git-accounts --json 2>/dev/null \
          | python3 -c 'import json, sys
d = json.load(sys.stdin)
print(int((d.get("registry") or {}).get("link_port") or d["app"]["port"]))' 2>/dev/null)" || port=""
  [ -n "${port}" ] || { say "${VIA}'s git app (DGO_FOLLOW_VIA) is not published to this office — nothing fetched"; return 1; }
  say "through the git app of ${VIA}, at its door :${port}"
  SRC="http://git-accounts.${VIA}:${port}${VIA_PATH}"
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
green_shas() {   # the commits of DGO_FOLLOW whose ${GATES} run succeeded, one per line; fails when none can be read
  if [ -n "${DGO_FOLLOW_GREEN_CMD:-}" ]; then "${DGO_FOLLOW_GREEN_CMD}"; return; fi
  local url slug tok ref="" api=""
  # Every green run, where the checkout can read GitHub's API. Never print the URL: it may carry a credential.
  url="$(git remote get-url origin 2>/dev/null)" || url=""
  case "${url}" in
    *github.com[:/]*)
      slug="$(printf '%s' "${url}" | sed -E 's#\.git$##; s#^.*github\.com[:/]##')"
      tok="$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill 2>/dev/null | sed -n 's/^password=//p')"
      api="$({ [ -z "${tok}" ] || printf 'header = "Authorization: Bearer %s"\n' "${tok}"; } \
        | curl -sf --max-time 30 -K - -H 'Accept: application/vnd.github+json' \
            "https://api.github.com/repos/${slug}/actions/workflows/${GATES}/runs?branch=${FOLLOW}&status=success&per_page=100" \
        | python3 -c 'import json, sys
for r in json.load(sys.stdin).get("workflow_runs", []):
    print(r["head_sha"])' 2>/dev/null)" || api="" ;;
  esac
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
  local n line model spared="" by
  model="$(model_services)" || model=""
  [ "${LOST_SPARE:-1}" = 0 ] || spared="$(leaning "$1" "$2")" || spared=""
  printf '%s\n' "$1" | good_names | while read -r n; do
    line="$(printf '%s\n' "$2" | awk -v n="${n}" '$1 == n')"
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
  stale_image_services
}

office_rebuild() {   # bbox run of exactly these services, logged: it builds what it brings up (--build, or the serial build)
  # its exit is the run's, fatal included (DGO-995): a build that fails here is now told, as the caller always meant
  if [ -n "${DGO_FOLLOW_RUN_CMD:-}" ]; then "${DGO_FOLLOW_RUN_CMD}" rebuild "$@"; return; fi
  "${REPO_ROOT}/bbox" run "$@" > "${STATE_DIR}/run-$(date -u '+%Y%m%dT%H%M%S')-rebuild.log" 2>&1
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
  say "declared: DGO_FOLLOW=${FOLLOW:-<empty: not following>}  DGO_BRANCH=${BRANCH:-<empty>}  gates: ${GATES}${VIA:+  via: the git app of ${VIA}}"
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
    [ -n "${unstage}" ] && say "would unstage left work the take does not touch (its text stays): ${unstage//$'\n'/ }"
    [ -n "${keep}" ] && say "would keep left work in a commit on ${BRANCH} first: ${keep//$'\n'/ }"
    say "then: bbox run, every healthy service compared ($(services | good_names | wc -l | tr -d ' ') healthy now), push or roll back"
    return 0
  fi
  room || return 0
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
  if ! apps_before="$(declared_apps "${prev}")" || ! apps_after="$(declared_apps "${merged}")"; then
    reset_keep "${prev}" 2>/dev/null || { finish failed "the declared apps cannot be read, and undoing the merge was refused"; return 1; }
    st_set TAKING "" MERGED "" BEFORE ""
    if [ -n "$(declared_apps "${prev}")" ]; then   # ours reads, the merged one does not: the target's fault, not retried
      st_set FAILED_TARGET "${tgt}" FAILED_AT "$(date -u '+%F %T UTC')" FAILED_HEAD ""
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
    reset_keep "${prev}" 2>/dev/null || { finish failed "the apps would change, and undoing the merge was refused"; return 1; }
    st_set TAKING "" MERGED "" BEFORE "" FAILED_TARGET "${tgt}" FAILED_AT "$(date -u '+%F %T UTC')" FAILED_HEAD ""
    tell "לא ניתן לעדכן: העדכון משנה אילו אפליקציות רצות כאן — ${OFFICE}" "${what} $(short "${tgt}") would change which apps this office runs (${plus:+on: ${plus}}${minus:+off: ${minus}}). That is this office's decision, not a merge's: nothing ran, ${BRANCH} is back at $(short "${prev}"). A session must take it by hand."
    finish blocked "the take would change the enabled apps (${plus:+on: ${plus}}${minus:+off: ${minus}})"; return 1
  fi
  say "took ${what} $(short "${tgt}") into ${BRANCH} — bringing the office up on it"
  rc=0; office_run take || rc=$?
  if after="$(settle)"; then bad="$(lost "${before}" "${after}")"; else bad="the services cannot be read"; fi
  [ "${rc}" = 0 ] || bad="${bad:+${bad}$'\n'}bbox run exited ${rc}"
  if [ -n "${bad}" ]; then rollback "${prev}" "${merged}" "${tgt}" "${bad//$'\n'/, }"; return 1; fi
  st_set VERIFIED "${merged}"     # healthy: what recover() trusts, origin's ref being no proof for an own-branch take
  # WHAT WAS MERGED IS WHAT RUNS (DGO-1356). A service whose image is older than its own build files runs the code
  # from before the take: measured 2026-11-05 on the Dell, dgo-extend and dgo-carry ran images from before the relay
  # its checkout had held for three days, so the relay line in its .env did nothing. Exactly those are built again;
  # a build that fails is said. The take stands either way: its code is merged and the office is healthy.
  local old rebuilt=1; old="$(old_images 2>/dev/null)" || old=""
  if [ -n "${old}" ]; then
    say "images older than their sources after the take: ${old} — building exactly these"
    # shellcheck disable=SC2086
    office_rebuild ${old} || { tell "שירותים רצים על קוד ישן אחרי עדכון — ${OFFICE}" "After taking ${what} $(short "${tgt}"), ${old} run images older than their sources and building them again failed (data/follow/run-*-rebuild.log): the code is merged, and those services run the code from before it." && rebuilt=0; }
  fi
  if [ "$(git rev-parse HEAD)" != "${merged}" ]; then moved_on_top "${tgt}"; return 1; fi
  local held=""; [ "$(git rev-parse -q --verify "refs/remotes/origin/${BRANCH}")" = "${merged}" ] && held=1
  # the merge itself, not HEAD: a commit landing between the check above and the push is never pushed unchecked
  if push_branch "${merged}"; then
    st_set TAKING "" MERGED "" BEFORE "" FAILED_TARGET "" FAILED_AT "" FAILED_HEAD "" PUSH_PENDING ""
    finish took "${what} $(short "${tgt}") into ${BRANCH} at $(short HEAD), healthy, $([ -n "${held}" ] && echo "origin's own commit (nothing to push)" || echo pushed)"
    [ "${rebuilt}" = 0 ] || told_took "${what}" "${tgt}"   # a failed rebuild's row names the take, and stays open
  else
    st_set TAKING "" MERGED "" BEFORE "" FAILED_TARGET "" FAILED_AT "" FAILED_HEAD "" PUSH_PENDING "${merged}"
    finish took "${what} $(short "${tgt}") into ${BRANCH}, healthy — the push was refused, the next cycle pushes again"
    tell "המשרד עודכן אבל הענף לא נדחף — ${OFFICE}" "${BRANCH} took ${what} $(short "${tgt}") and is healthy, but pushing it${VIA:+ through ${VIA}} was refused; the next cycle pushes again."
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

# ── one cycle ─────────────────────────────────────────────────────────────────────────────────────
cycle() {
  local cpus load gd green target
  if [ "${DRY}" != 1 ]; then
    # under a heavy job the heal waits for the next trigger or cycle — said, since not every heavy job runs an `up`
    if [ "$(heavy_slot_status)" = free ]; then office_heal; else say "the heal is put off: a heavy job holds the slot"; fi
  fi
  [ "${HEAL}" = 0 ] || return 0
  [ -n "${FOLLOW}" ] || { say "DGO_FOLLOW is empty — this office does not follow"; return 0; }
  [ -n "${BRANCH}" ] || { tell "לא ניתן לעקוב: DGO_BRANCH ריק — ${OFFICE}" "DGO_FOLLOW=${FOLLOW} is declared, but the office's own branch (DGO_BRANCH) is not: nothing is merged without it."; return 1; }
  mkdir -p "${REPO_ROOT}/data/.locks" "${STATE_DIR}" || return 1
  if [ "$(heavy_slot_status)" != free ]; then finish skipped "a heavy job holds the slot: $(heavy_slot_status)"; return 0; fi
  cpus="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"
  load="$(cut -d' ' -f1 /proc/loadavg 2>/dev/null || echo 0)"
  if awk -v l="${load}" -v c="${cpus}" -v m="${MAX_LOAD}" 'BEGIN {exit !(l > (m == "" ? c : m))}'; then
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
  if [ -n "${VIA}" ] && [ -z "${VIA_PATH}" ]; then   # a declaration missing: no cycle will fix it by itself
    tell "לא ניתן לעקוב: DGO_FOLLOW_VIA_PATH ריק — ${OFFICE}" "DGO_FOLLOW_VIA=${VIA} is declared, but not the path of the repository on its git app (DGO_FOLLOW_VIA_PATH=/git/gh/<account>/<owner>/<repo>.git). Nothing was fetched."
    finish blocked "DGO_FOLLOW_VIA=${VIA} without DGO_FOLLOW_VIA_PATH"; return 1
  fi
  resolve_src || { finish skipped "${VIA}'s git app cannot be reached (DGO_FOLLOW_VIA)"; return 0; }
  git fetch -q "${SRC}" "+refs/heads/${FOLLOW}:refs/remotes/origin/${FOLLOW}" 2>/dev/null \
    || { finish skipped "fetch of ${FOLLOW} failed${VIA:+ (through ${VIA})}"; return 0; }
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
    st_set TAKING "" MERGED "" VERIFIED "" BEFORE "" WHY "" FAILED_TARGET "" FAILED_AT "" FAILED_HEAD ""
    say "follow: the open take and the failed target are forgotten — the next cycle follows ${FOLLOW:-<nothing>} again" ;;
  -h|--help) sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
  *) die "usage: bbox follow [--dry-run] | heal | status | install | clear" ;;
esac
