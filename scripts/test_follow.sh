#!/usr/bin/env bash
# test_follow.sh — scripts/follow.sh takes only a green dgo-stable, keeps it only when the office stays
# healthy, never loses an office's own changes, and settles a take it was stopped in the middle of.
#
#     bash scripts/test_follow.sh
#
# A throwaway origin (bare) with dgo-stable and the office branch o-dgo, and the office's checkout cloned from it.
# Everything follow.sh would ask of a live office is played by a stub: the gates (a file of green shas), `bbox run`
# (an exit code, what it does to the services, and optionally something worse), the services (a file; a marker makes
# reading them fail), the enabled apps (read from platform.state.yaml) and the notice centre (a file of rows). Each
# case states the shape it reproduces. Needs bash 4, git, flock and pkill; no engine, no network.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
T="$(mktemp -d)"
trap 'rm -rf "${T}"' EXIT
# follow.sh runs from a copy it makes in $TMPDIR, and the killed-cycle cases below kill by that copy's name. The
# test's own TMPDIR keeps the kill to the test's cycles: with /tmp, a run on vps1 killed vps1's live cycle in the
# middle of its take's `bbox run` and left 16 apps Created (2026-11-03 02:35:52).
mkdir -p "${T}/tmp"; export TMPDIR="${T}/tmp"
fails=0
say() { printf '%s  %s\n' "$1" "$2"; }
ok() { if eval "$2"; then say PASS "$1"; else say FAIL "$1"; sed 's/^/      | /' "${T}/out" | tail -6; fails=$((fails + 1)); fi; }

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t.invalid GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t.invalid
export GIT_CONFIG_GLOBAL="${T}/gitconfig" GIT_CONFIG_NOSYSTEM=1
printf '[init]\n\tdefaultBranch = main\n' > "${GIT_CONFIG_GLOBAL}"
mkdir -p "${T}/bin"
cat > "${T}/bin/green" <<'EOF'
#!/bin/sh
cat "${STUB}/green" 2>/dev/null
EOF
cat > "${T}/bin/run" <<'EOF'
#!/bin/sh
# bbox run: records itself, leaves the services as health.<take|rollback> says, does what do.<take> says
echo "$1" >> "${STUB}/runs"
echo "$1:${BBOX_ALLOW_ROLLBACK:-unset}" >> "${STUB}/allow"
[ -f "${STUB}/health.$1" ] && cp "${STUB}/health.$1" "${STUB}/health"
[ -f "${STUB}/do.$1" ] && . "${STUB}/do.$1"
exit "$(cat "${STUB}/rc.$1" 2>/dev/null || echo 0)"
EOF
cat > "${T}/bin/health" <<'EOF'
#!/bin/sh
[ -e "${STUB}/health.unreadable" ] && exit 1
cat "${STUB}/health"
EOF
cat > "${T}/bin/model" <<'EOF'
#!/bin/sh
cat "${STUB}/model"
EOF
cat > "${T}/bin/busy" <<'EOF'
#!/bin/sh
cat "${STUB}/busy" 2>/dev/null
EOF
cat > "${T}/bin/notify" <<'EOF'
#!/bin/sh
printf '%s | %s | %s\n' "$1" "$2" "$3" >> "${STUB}/notices"
EOF
chmod +x "${T}/bin/"*
export STUB="${T}/stub"
export DGO_FOLLOW_GREEN_CMD="${T}/bin/green" DGO_FOLLOW_RUN_CMD="${T}/bin/run" DGO_FOLLOW_HEALTH_CMD="${T}/bin/health" \
       DGO_FOLLOW_MODEL_CMD="${T}/bin/model" DGO_FOLLOW_NOTIFY_CMD="${T}/bin/notify" DGO_FOLLOW_BUSY_CMD="${T}/bin/busy" \
       DGO_FOLLOW_MAX_LOAD=100000 DGO_FOLLOW_SETTLE=0
unset DGO_FOLLOW_COPY DGO_FOLLOW_LOCKED

# fresh — origin with dgo-stable and o-dgo at one commit, the office cloned on o-dgo, two healthy services, nothing green
fresh() {
  rm -rf "${T}/origin.git" "${T}/office" "${T}/seed" "${T}/side" "${T}/peer" "${STUB}"; mkdir -p "${STUB}"
  git init -q --bare "${T}/origin.git"
  git init -q "${T}/seed" && cd "${T}/seed" || exit 1
  printf 'apps:\n  a: { state: enabled }\n  e: { enabled: false }\n\n\n\nremote:\n  fetched: 1\n' > platform.state.yaml
  printf 'one\n' > code.txt; printf 'x\n' > other.txt
  mkdir -p apps/x && printf 'services:\n  web:\n    image: w\n  db:\n    image: d\n  init:\n    image: i\n' > apps/x/docker-compose.yml
  printf '.env\ndata/\n*.local\n' > .gitignore
  git add -A && git commit -qm base && git branch dgo-stable && git branch o-dgo
  git push -q "${T}/origin.git" dgo-stable o-dgo
  cd "${T}" && git clone -q -b o-dgo "${T}/origin.git" office
  printf 'DEPLOYMENT_NAME=t\nDGO_OFFICE_ID=test\nDGO_BRANCH=o-dgo\nDGO_FOLLOW=dgo-stable\n' > "${T}/office/.env"
  printf 'web running healthy\ndb running -\ninit done -\n' > "${STUB}/health"
  printf 'web\ndb\ninit\n' > "${STUB}/model"
  O="${T}/office"
}
# stable <file> <text> [green] — a commit on origin's dgo-stable (green when asked), from a side clone; prints its sha
stable() {
  [ -d "${T}/side" ] || git clone -q -b dgo-stable "${T}/origin.git" "${T}/side"
  ( cd "${T}/side" && git pull -q origin dgo-stable && printf '%s\n' "$2" > "$1" && git add "$1" && git commit -qm "stable: $1" && git push -q origin dgo-stable )
  [ "${3:-}" = green ] && git -C "${T}/side" rev-parse HEAD >> "${STUB}/green"
  git -C "${T}/side" rev-parse HEAD
}
follow() { REPO_ROOT="${O}" bash "${HERE}/follow.sh" "$@" > "${T}/out" 2>&1; }
head_of() { git -C "${O}" rev-parse HEAD; }
origin_of() { git -C "${T}/origin.git" rev-parse "$1"; }
has() { git -C "${O}" merge-base --is-ancestor "$1" HEAD; }
notices() { if [ -f "${STUB}/notices" ]; then wc -l < "${STUB}/notices" | tr -d ' '; else echo 0; fi; }
runs() { if [ -f "${STUB}/runs" ]; then tr '\n' ' ' < "${STUB}/runs"; fi; }
st() { grep -E "^$1=" "${O}/data/follow/state" 2>/dev/null | tail -1 | cut -d= -f2-; }

# ── taking ─────────────────────────────────────────────────────────────────────────────────────────
# 1. DGO_FOLLOW empty: nothing at all
fresh; sed -i 's/^DGO_FOLLOW=.*/DGO_FOLLOW=/' "${O}/.env"; h="$(head_of)"; stable code.txt two green >/dev/null; follow
ok "not following: nothing merged" '[ "$(head_of)" = "${h}" ] && grep -q "does not follow" "${T}/out"'

# 2. dgo-stable moved but nothing is green: the office stays where it is
fresh; h="$(head_of)"; stable code.txt two >/dev/null; follow
ok "nothing green: not taken" '[ "$(head_of)" = "${h}" ] && [ "$(notices)" = 0 ]'

# 3. a green commit: taken, one run, pushed to the office's own branch, nobody told; then current
fresh; g="$(stable code.txt two green)"; follow
ok "green: taken, one run, pushed, nobody told" 'has "${g}" && [ "$(runs)" = "take " ] && [ "$(origin_of o-dgo)" = "$(head_of)" ] && [ "$(notices)" = 0 ]'
ok "green: dgo-stable itself untouched" '[ "$(origin_of dgo-stable)" = "${g}" ]'
follow
ok "then current: no second run" '[ "$(runs)" = "take " ] && [ "$(st LAST_RESULT)" = current ]'

# 3b. an app says it is in use (a meeting): nothing merged, nothing run, nobody told; taken once it is over
fresh; h="$(head_of)"; g="$(stable code.txt two green)"; echo "meet: 1 meeting(s) in progress on the video bridge" > "${STUB}/busy"; follow
ok "busy: not taken, no run, nobody told" '[ "$(head_of)" = "${h}" ] && [ "$(runs)" = "" ] && [ "$(notices)" = 0 ] && grep -q "meeting" <<<"$(st LAST_DETAIL)"'
rm -f "${STUB}/busy"; follow
ok "busy: taken once the meeting is over" 'has "${g}"'

# 4. a newer commit that is NOT green after a green one: only the green one is taken
fresh; g="$(stable code.txt two green)"; n="$(stable other.txt y)"; follow
ok "the newest green, not the newest" 'has "${g}" && ! has "${n}"'

# 5. origin's o-dgo is ahead (pushed from elsewhere): a take of its own, run and checked; dgo-stable the next cycle
fresh; git clone -q -b o-dgo "${T}/origin.git" "${T}/peer"
( cd "${T}/peer" && printf 'p\n' > peer.txt && git add peer.txt && git commit -qm peer && git push -q origin o-dgo ); p="$(git -C "${T}/peer" rev-parse HEAD)"
g="$(stable code.txt two green)"; follow
ok "own branch ahead: taken alone, with a run" 'has "${p}" && ! has "${g}" && [ "$(runs)" = "take " ]'
follow
ok "own branch ahead: dgo-stable the cycle after" 'has "${g}" && [ "$(origin_of o-dgo)" = "$(head_of)" ]'

# ── health ─────────────────────────────────────────────────────────────────────────────────────────
# 6. a service turns unhealthy: rolled back, run again, never pushed, told once, not retried; a newer green is
fresh; h="$(head_of)"; g="$(stable code.txt two green)"
printf 'web running unhealthy\ndb running -\ninit done -\n' > "${STUB}/health.take"; cp "${STUB}/health" "${STUB}/health.rollback"; follow
ok "unhealthy: rolled back and run again" '[ "$(head_of)" = "${h}" ] && [ "$(cat "${O}/code.txt")" = one ] && [ "$(runs)" = "take rollback " ]'
ok "unhealthy: only the rollback runs as going back on purpose (the deploy ledger lets it)" '[ "$(tr "\n" " " < "${STUB}/allow")" = "take:0 rollback:1 " ]'
ok "unhealthy: origin/o-dgo untouched" '[ "$(origin_of o-dgo)" = "${h}" ]'
ok "unhealthy: told once, with the service, healthy again" '[ "$(notices)" = 1 ] && grep -q "web running unhealthy" "${STUB}/notices" && grep -q "healthy again" "${STUB}/notices"'
DGO_FOLLOW_STALE_S=0 follow
ok "unhealthy: the same commit waits, no new run or notice, no stale alarm" '[ "$(head_of)" = "${h}" ] && [ "$(runs)" = "take rollback " ] && [ "$(notices)" = 1 ] && [ "$(st LAST_RESULT)" = waiting ]'
rm -f "${STUB}/health.take"; g2="$(stable code.txt three green)"; follow
ok "a newer green after a failure: taken, the row closed" 'has "${g2}" && grep -q "^info" <<<"$(tail -1 "${STUB}/notices")"'

# 7. a service vanishes (the merge removed or disabled it): rolled back
fresh; h="$(head_of)"; stable code.txt two green >/dev/null; printf 'web running healthy\ninit done -\n' > "${STUB}/health.take"
cp "${STUB}/health" "${STUB}/health.rollback"; follow
ok "a vanished service: rolled back, named" '[ "$(head_of)" = "${h}" ] && grep -q "db gone" "${STUB}/notices"'
# …but one the take RETIRED (its compose key removed by the take, and gone from the compiled model) is a release
fresh; git clone -q -b dgo-stable "${T}/origin.git" "${T}/side"
( cd "${T}/side" && sed -i '/^  db:$/,+1d' apps/x/docker-compose.yml && git commit -qam "stable: retire db" && git push -q origin dgo-stable )
g="$(git -C "${T}/side" rev-parse HEAD)"; echo "${g}" >> "${STUB}/green"
printf 'web running healthy\ninit done -\n' > "${STUB}/health.take"; printf 'printf "web\\\\ninit\\\\n" > "${STUB}/model"\n' > "${STUB}/do.take"; follow
ok "a retired service: taken" 'has "${g}" && [ "$(notices)" = 0 ]'
# …while one that only dropped out of the model (the take did not remove it: a compiler or app.json gone wrong) is not
fresh; h="$(head_of)"; stable code.txt two green >/dev/null; printf 'web running healthy\ninit done -\n' > "${STUB}/health.take"
printf 'printf "web\\\\ninit\\\\n" > "${STUB}/model"\n' > "${STUB}/do.take"; cp "${STUB}/health" "${STUB}/health.rollback"; follow
ok "dropped from the model by accident: rolled back" '[ "$(head_of)" = "${h}" ] && grep -q "db gone" "${STUB}/notices"'

# 8. the services cannot be read after the take (dc broken by the merge): rolled back, never called healthy
fresh; h="$(head_of)"; stable code.txt two green >/dev/null; printf 'touch "${STUB}/health.unreadable"\n' > "${STUB}/do.take"
printf 'rm -f "${STUB}/health.unreadable"\n' > "${STUB}/do.rollback"; follow
ok "unreadable services: rolled back" '[ "$(head_of)" = "${h}" ] && [ "$(origin_of o-dgo)" = "${h}" ] && grep -q "cannot be read" "${STUB}/notices"'

# …and zero services BEFORE (a compile that resolved nothing, gate G7's shape) is no baseline: nothing is taken
fresh; h="$(head_of)"; stable code.txt two green >/dev/null; : > "${STUB}/health"; follow
ok "zero services before: not taken, no run" '[ "$(head_of)" = "${h}" ] && [ "$(runs)" = "" ] && [ "$(st LAST_RESULT)" = skipped ]'

# 9. bbox run itself fails: rolled back the same way
fresh; h="$(head_of)"; stable code.txt two green >/dev/null; echo 1 > "${STUB}/rc.take"; follow
ok "bbox run exit 1: rolled back and told" '[ "$(head_of)" = "${h}" ] && grep -q "bbox run exited 1" "${STUB}/notices"'

# ── the office's own work ──────────────────────────────────────────────────────────────────────────
# 10. an uncommitted change in a file the target changes: nothing merged, the change intact, told once over two cycles
fresh; h="$(head_of)"; stable code.txt two green >/dev/null; printf 'mine\n' > "${O}/code.txt"; follow; follow
ok "local change: not merged, kept, told once" '[ "$(head_of)" = "${h}" ] && [ "$(cat "${O}/code.txt")" = mine ] && [ "$(runs)" = "" ] && [ "$(notices)" = 1 ] && grep -q code.txt "${STUB}/notices"'
# …a change in a file the target does not touch is no obstacle, and stays uncommitted
fresh; g="$(stable code.txt two green)"; printf 'mine\n' > "${O}/other.txt"; follow
ok "unrelated local change: taken, still uncommitted" 'has "${g}" && [ "$(cat "${O}/other.txt")" = mine ] && [ -n "$(git -C "${O}" diff --name-only HEAD -- other.txt)" ]'

# 11. the target renames a file that is modified here: refused (renames count as both paths)
fresh; h="$(head_of)"
( cd "${T}" && git clone -q -b dgo-stable "${T}/origin.git" side && cd side && git mv other.txt other2.txt && git commit -qm "stable: rename" && git push -q origin dgo-stable )
git -C "${T}/side" rev-parse HEAD >> "${STUB}/green"; printf 'mine\n' > "${O}/other.txt"; follow
ok "renamed under a local change: not merged, kept" '[ "$(head_of)" = "${h}" ] && [ "$(cat "${O}/other.txt")" = mine ] && grep -q other.txt "${STUB}/notices"'

# 12. staged changes: refused, not blamed on the target; taken once unstaged
fresh; h="$(head_of)"; g="$(stable code.txt two green)"; printf 'z\n' > "${O}/staged.txt"; git -C "${O}" add staged.txt; follow
ok "staged changes: not merged, not a failed target" '[ "$(head_of)" = "${h}" ] && [ -z "$(st FAILED_TARGET)" ] && grep -q staged "${STUB}/notices"'
git -C "${O}" reset -q staged.txt; follow
ok "staged changes: taken once unstaged" 'has "${g}"'

# 13. a file the target adds is already here (an ignored file the office keeps): refused, the file intact
fresh; h="$(head_of)"; stable keep.local tracked green >/dev/null; printf 'office data\n' > "${O}/keep.local"; follow
ok "an existing file where the target adds one: kept, not merged" '[ "$(head_of)" = "${h}" ] && [ "$(cat "${O}/keep.local")" = "office data" ] && [ -z "$(st FAILED_TARGET)" ]'
# …but a file the office already TRACKS (a cherry-pick of the same commit) is no obstacle
fresh; g="$(stable added.txt same green)"
( cd "${O}" && git fetch -q origin dgo-stable && git cherry-pick -x "${g}" >/dev/null && git push -q origin o-dgo ); follow
ok "a file already tracked through a cherry-pick: taken" 'has "${g}" && [ "$(notices)" = 0 ]'

# 14. the office's own platform.state.yaml, which dgo-stable also changes: committed first, both kept
fresh; sed -i 's/fetched: 1/fetched: 2/' "${O}/platform.state.yaml"
( cd "${T}" && git clone -q -b dgo-stable "${T}/origin.git" side && cd side \
  && sed -i 's/  a: { state: enabled }/  a: { state: enabled }\n  b: { state: disabled }/' platform.state.yaml \
  && git commit -qam "stable: app b, off" && git push -q origin dgo-stable )
git -C "${T}/side" rev-parse HEAD >> "${STUB}/green"; follow
ok "platform state: dgo-stable's line and the office's own both kept" 'grep -q "b: { state: disabled }" "${O}/platform.state.yaml" && grep -q "fetched: 2" "${O}/platform.state.yaml"'
ok "platform state: committed on o-dgo, nothing left uncommitted" '[ -z "$(git -C "${O}" diff --name-only HEAD)" ] && grep -q "own platform state" <<<"$(git -C "${O}" log --format=%s)"'

# 15. dgo-stable would change WHICH apps run here (another office's state): undone before anything runs, told
fresh; h="$(head_of)"
( cd "${T}" && git clone -q -b dgo-stable "${T}/origin.git" side && cd side \
  && sed -i 's/  a: { state: enabled }/  a: { state: enabled }\n  c: { state: enabled }/' platform.state.yaml \
  && git commit -qam "stable: app c, on" && git push -q origin dgo-stable )
git -C "${T}/side" rev-parse HEAD >> "${STUB}/green"; follow
ok "apps would change: nothing ran, back where it was, told +c" '[ "$(head_of)" = "${h}" ] && [ "$(runs)" = "" ] && grep -q "on: c" "${STUB}/notices"'
# …and in the older `enabled: true` form too (most of the real file is written that way)
fresh; h="$(head_of)"
( cd "${T}" && git clone -q -b dgo-stable "${T}/origin.git" side && cd side \
  && sed -i 's/  e: { enabled: false }/  e: { enabled: true }/' platform.state.yaml && git commit -qam "stable: app e, on" && git push -q origin dgo-stable )
git -C "${T}/side" rev-parse HEAD >> "${STUB}/green"; follow
ok "apps would change (enabled: true form): nothing ran, told +e" '[ "$(head_of)" = "${h}" ] && [ "$(runs)" = "" ] && grep -q "on: e" "${STUB}/notices"'
# …while the office's OWN branch enabling an app (pushed from elsewhere) is its own decision: taken
fresh; git clone -q -b o-dgo "${T}/origin.git" "${T}/peer"
( cd "${T}/peer" && sed -i 's/  a: { state: enabled }/  a: { state: enabled }\n  d: { state: enabled }/' platform.state.yaml \
  && git commit -qam "office: app d, on" && git push -q origin o-dgo ); p="$(git -C "${T}/peer" rev-parse HEAD)"; follow
ok "own branch enabling an app: taken" 'has "${p}" && [ "$(notices)" = 0 ]'

# 16. a conflict with the office's own commit: aborted, unchanged, no merge left in flight, told
fresh; ( cd "${O}" && printf 'office\n' > code.txt && git commit -qam "office: code" && git push -q origin o-dgo ); h="$(head_of)"
stable code.txt stable green >/dev/null; follow
ok "conflict: aborted, unchanged, told the file" '[ "$(head_of)" = "${h}" ] && [ ! -e "${O}/.git/MERGE_HEAD" ] && [ -z "$(git -C "${O}" diff --name-only HEAD)" ] && grep -q code.txt "${STUB}/notices"'

# 16b. content dgo-stable itself carried into the office BY CONTENT (a cherry-pick, the release line carrying a branch),
#      then changed again on dgo-stable: the merge base never moved, so the files conflict (add/add, modify/modify) —
#      but the office's versions are ones dgo-stable had, so dgo-stable's are taken (vps1-dgo, 2026-11-03)
fresh; c1="$(stable carried.txt v1)"; c2="$(stable code.txt two)"
( cd "${O}" && git fetch -q origin dgo-stable && git show "${c1}:carried.txt" > carried.txt && git show "${c2}:code.txt" > code.txt \
  && git add carried.txt code.txt && git commit -qm "office: dgo-stable's files, by content" && git push -q origin o-dgo )
stable code.txt three >/dev/null; g="$(stable carried.txt v2 green)"; follow
ok "carried content: taken, dgo-stable's versions win, nobody told" 'has "${g}" && [ "$(cat "${O}/carried.txt")" = v2 ] && [ "$(cat "${O}/code.txt")" = three ] && [ "$(notices)" = 0 ] && [ "$(origin_of o-dgo)" = "$(head_of)" ]'
ok "carried content: the merge says what it took" 'grep -q "carried, its versions taken: carried.txt code.txt" <<<"$(git -C "${O}" log -1 --format=%s)"'
# …but a path among them that the office DID change itself (a version dgo-stable never had) stops the take, as before
fresh; c1="$(stable carried.txt v1)"
( cd "${O}" && git fetch -q origin dgo-stable && git show "${c1}:carried.txt" > carried.txt && printf 'office\n' > other.txt \
  && git add carried.txt other.txt && git commit -qm "office: carried + its own" && git push -q origin o-dgo ); h="$(head_of)"
stable other.txt stable >/dev/null; stable carried.txt v2 green >/dev/null; follow
ok "carried and own together: stopped, nothing taken, told the files" '[ "$(head_of)" = "${h}" ] && [ ! -e "${O}/.git/MERGE_HEAD" ] && [ "$(cat "${O}/other.txt")" = office ] && grep -q other.txt "${STUB}/notices"'
# …and an office that put a file back to an OLD dgo-stable version on purpose (one from before the merge base) changed
# it itself: not carried, the take stops (the second reader's case)
fresh; stable code.txt old green >/dev/null; follow
( cd "${O}" && printf 'one\n' > code.txt && git commit -qam "office: the seed's code back, on purpose" && git push -q origin o-dgo ); h="$(head_of)"
stable code.txt new green >/dev/null; follow
ok "a deliberate revert to an old dgo-stable version: stopped, kept" '[ "$(head_of)" = "${h}" ] && [ "$(cat "${O}/code.txt")" = one ] && grep -q code.txt "${STUB}/notices"'

# ── a take that did not end cleanly ────────────────────────────────────────────────────────────────
# 17. the rollback is refused (a file the take moved was changed meanwhile): never "current", retried, then settled
fresh; h="$(head_of)"; g="$(stable code.txt two green)"
printf 'web running unhealthy\ndb running -\ninit done -\n' > "${STUB}/health.take"; cp "${STUB}/health" "${STUB}/health.rollback"
printf 'printf "edited\\n" > "${REPO_ROOT}/code.txt"\n' > "${STUB}/do.take"; follow
ok "refused rollback: told, the take stays open" '[ "$(head_of)" != "${h}" ] && grep -q "refused by git" "${STUB}/notices" && [ -n "$(st TAKING)" ]'
n1="$(notices)"; follow
ok "refused rollback: the next cycle is not current, no all-clear, no second row" '[ "$(st LAST_RESULT)" != current ] && [ "$(notices)" = "${n1}" ] && ! grep -q "^info" "${STUB}/notices"'
git -C "${O}" checkout -q -- code.txt; follow
ok "refused rollback: once the file is back, rolled back and run" '[ "$(head_of)" = "${h}" ] && [ -z "$(st TAKING)" ] && [ "$(st FAILED_TARGET)" = "${g}" ]'

# 18. the cycle is killed after the merge (a reboot, the unit's timeout): the next cycle rolls the unverified take back
fresh; h="$(head_of)"; g="$(stable code.txt two green)"; printf 'pkill -KILL -f "%s/dgo-follow\\\\."\n' "${TMPDIR}" > "${STUB}/do.take"; follow
ok "killed mid-take: left merged, unpushed" 'has "${g}" && [ "$(origin_of o-dgo)" = "${h}" ]'
rm -f "${STUB}/do.take"; follow
ok "killed mid-take: the next cycle rolls it back, never current" '[ "$(head_of)" = "${h}" ] && [ "$(st FAILED_TARGET)" = "${g}" ] && grep -q "stopped before its health check" "${STUB}/notices"'
# …and killed during the ROLLBACK's run: the next cycle runs it again and tells the owner, with the reason
fresh; h="$(head_of)"; g="$(stable code.txt two green)"
printf 'web running unhealthy\ndb running -\ninit done -\n' > "${STUB}/health.take"; cp "${STUB}/health" "${STUB}/health.rollback"
printf 'pkill -KILL -f "%s/dgo-follow\\\\."\n' "${TMPDIR}" > "${STUB}/do.rollback"; follow; rm -f "${STUB}/do.rollback"
ok "killed mid-rollback: back at the commit before, nobody told yet" '[ "$(head_of)" = "${h}" ] && [ "$(notices)" = 0 ]'
follow
ok "killed mid-rollback: the next cycle runs it and tells why" '[ "$(runs)" = "take rollback rollback " ] && grep -q "web running unhealthy" "${STUB}/notices" && [ -z "$(st TAKING)" ]'

# 19. a commit lands on top during the take: nothing pushed, sticky until a session clears it
fresh; h="$(head_of)"; g="$(stable code.txt two green)"
printf '( cd "${REPO_ROOT}" && printf "agent\\n" > agent.txt && git add agent.txt && git commit -qm agent )\n' > "${STUB}/do.take"; follow
ok "HEAD moved during the take: not pushed, told" '[ "$(origin_of o-dgo)" = "${h}" ] && grep -q "landed on top" "${STUB}/notices"'
rm -f "${STUB}/do.take"; n1="$(notices)"; follow
ok "HEAD moved: the next cycle stays stopped, no second row" '[ "$(st LAST_RESULT)" = blocked ] && [ "$(notices)" = "${n1}" ] && [ "$(runs)" = "take " ]'
REPO_ROOT="${O}" bash "${HERE}/follow.sh" clear >/dev/null 2>&1; follow
ok "HEAD moved: after \`follow clear\`, following again" '[ "$(st LAST_RESULT)" = current ]'

# 20. the push is refused: healthy, kept, retried by the next cycle, then the row is closed
fresh; g="$(stable code.txt two green)"; printf '#!/bin/sh\n[ -e "%s/reject" ] && exit 1\nexit 0\n' "${STUB}" > "${T}/origin.git/hooks/pre-receive"
chmod +x "${T}/origin.git/hooks/pre-receive"; touch "${STUB}/reject"; follow
ok "push refused: taken, told, pending" 'has "${g}" && [ "$(origin_of o-dgo)" != "$(head_of)" ] && [ "$(st PUSH_PENDING)" = "$(head_of)" ] && [ "$(notices)" = 1 ]'
rm -f "${STUB}/reject"; follow
ok "push refused: pushed by the next cycle, the row closed" '[ "$(origin_of o-dgo)" = "$(head_of)" ] && grep -q "^info" <<<"$(tail -1 "${STUB}/notices")"'

# ── the rest ───────────────────────────────────────────────────────────────────────────────────────
# 21. --dry-run: says what it would do, writes nothing
fresh; h="$(head_of)"; stable code.txt two green >/dev/null; follow --dry-run
ok "dry run: nothing merged, run, written or told" '[ "$(head_of)" = "${h}" ] && [ "$(runs)" = "" ] && [ ! -e "${O}/data/follow/state" ] && [ "$(notices)" = 0 ] && grep -q "would take" "${T}/out"'

# 22. the checkout and origin's o-dgo diverged: nothing merged, told
fresh; git clone -q -b o-dgo "${T}/origin.git" "${T}/peer"
( cd "${T}/peer" && printf 'p\n' > peer.txt && git add peer.txt && git commit -qm peer && git push -q origin o-dgo )
( cd "${O}" && printf 'l\n' > local.txt && git add local.txt && git commit -qm local ); h="$(head_of)"
stable code.txt two green >/dev/null; follow
ok "diverged own branch: nothing merged, told" '[ "$(head_of)" = "${h}" ] && grep -q "have each moved" "${STUB}/notices"'

# 23. not on its own branch: nothing merged, told
fresh; git -C "${O}" checkout -q -b elsewhere; h="$(head_of)"; stable code.txt two green >/dev/null; follow
ok "wrong branch: nothing merged, told" '[ "$(head_of)" = "${h}" ] && grep -q "not o-dgo" "${STUB}/notices"'

# 24. another cycle holds the lock: this one leaves at once and writes nothing
fresh; stable code.txt two green >/dev/null; mkdir -p "${O}/data/.locks"
flock "${O}/data/.locks/follow" sleep 5 & sleep 0.5; follow; wait
ok "locked: leaves at once, nothing written" 'grep -q "another follow cycle is running" "${T}/out" && [ ! -e "${O}/data/follow/state" ]'

# 25. a day of cycles put off (here: no gate readable), with no failure open: the owner is told once
fresh; stable code.txt two >/dev/null; follow; DGO_FOLLOW_STALE_S=0 follow; DGO_FOLLOW_STALE_S=0 follow
ok "put off for a day: told once" '[ "$(notices)" = 1 ] && grep -q "יותר מיממה" "${STUB}/notices"'

echo
[ "${fails}" = 0 ] && echo "test_follow: all passed" || echo "test_follow: ${fails} FAILED"
exit $((fails > 0))
