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
echo "$1:${BBOX_DISK_ADMITTED:-unset}" >> "${STUB}/admitted"
echo "$1:${BBOX_ALLOW_ROLLBACK:-unset}" >> "${STUB}/allow"
[ "$1" = rebuild ] && echo "$*" >> "${STUB}/rebuilt"
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
cat > "${T}/bin/deps" <<'EOF'
#!/bin/sh
# the compiled model's depends_on edges, "<service> <dependency>" (none unless a case writes deps)
cat "${STUB}/deps" 2>/dev/null
EOF
cat > "${T}/bin/old" <<'EOF'
#!/bin/sh
cat "${STUB}/old" 2>/dev/null
EOF
cat > "${T}/bin/busy" <<'EOF'
#!/bin/sh
cat "${STUB}/busy" 2>/dev/null
EOF
cat > "${T}/bin/notify" <<'EOF'
#!/bin/sh
[ -e "${STUB}/notify.fail" ] && exit 1   # the notice centre down
printf '%s | %s | %s | %s\n' "$1" "$2" "$3" "$4" >> "${STUB}/notices"
EOF
cat > "${T}/bin/disk" <<'EOF'
#!/bin/sh
# the disk floor (lib.sh disk_admit / disk_reclaim / disk_free_gb): under the floor while disk.low exists
case "$1" in
  admit)   [ ! -e "${STUB}/disk.low" ] ;;
  reclaim) echo reclaim >> "${STUB}/reclaims" ;;
  free)    cat "${STUB}/disk.free" 2>/dev/null || echo 99 ;;
esac
EOF
cat > "${T}/bin/heal" <<'EOF'
#!/bin/sh
# lib.sh netns_rejoin: what a reboot left out of a shared network namespace, recreated — here only counted
echo heal >> "${STUB}/heals"
EOF
cat > "${T}/bin/disk" <<'EOF'
#!/bin/sh
# the disk floor (lib.sh disk_admit / disk_reclaim / disk_free_gb): under the floor while disk.low exists
case "$1" in
  admit)   [ ! -e "${STUB}/disk.low" ] ;;
  reclaim) echo reclaim >> "${STUB}/reclaims" ;;
  free)    cat "${STUB}/disk.free" 2>/dev/null || echo 99 ;;
esac
EOF
chmod +x "${T}/bin/"*
export STUB="${T}/stub"
export DGO_FOLLOW_GREEN_CMD="${T}/bin/green" DGO_FOLLOW_RUN_CMD="${T}/bin/run" DGO_FOLLOW_HEALTH_CMD="${T}/bin/health" \
       DGO_FOLLOW_MODEL_CMD="${T}/bin/model" DGO_FOLLOW_NOTIFY_CMD="${T}/bin/notify" DGO_FOLLOW_BUSY_CMD="${T}/bin/busy" \
       DGO_FOLLOW_OLD_IMAGES_CMD="${T}/bin/old" DGO_FOLLOW_DEPS_CMD="${T}/bin/deps" \
       DGO_FOLLOW_MAX_LOAD=100000 DGO_FOLLOW_SETTLE=0
unset DGO_FOLLOW_COPY DGO_FOLLOW_LOCKED
export DGO_FOLLOW_DISK_CMD="${T}/bin/disk"
export DGO_FOLLOW_HEAL_CMD="${T}/bin/heal"

# fresh — origin with dgo-stable and o-dgo at one commit, the office cloned on o-dgo, two healthy services, nothing green
fresh() {
  rm -rf "${T}/origin.git" "${T}/via.git" "${T}/office" "${T}/seed" "${T}/side" "${T}/peer" "${STUB}"; mkdir -p "${STUB}"
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
# a good take of dgo-stable is told, once, in a row of its own (follow:took:<office>:<sha>) — DGO-1329: «every
# important event»; the line is the taken commit's subject
took_told() { local s; s="$(git -C "${O}" rev-parse --short "$1")"; [ "$(notices)" = 1 ] && grep -q "^info | המשרד התעדכן ל־dgo-stable ${s} | .* | took:test:${s}$" "${STUB}/notices"; }
# stable_said <file> <text> <message> — a green commit on dgo-stable with this commit message; prints its sha
stable_said() {
  [ -d "${T}/side" ] || git clone -q -b dgo-stable "${T}/origin.git" "${T}/side"
  ( cd "${T}/side" && git pull -q origin dgo-stable && printf '%s\n' "$2" > "$1" && git add "$1" && git commit -qm "$3" && git push -q origin dgo-stable )
  git -C "${T}/side" rev-parse HEAD >> "${STUB}/green"
  git -C "${T}/side" rev-parse HEAD
}

# ── taking ─────────────────────────────────────────────────────────────────────────────────────────
# 1. DGO_FOLLOW empty: nothing at all
fresh; sed -i 's/^DGO_FOLLOW=.*/DGO_FOLLOW=/' "${O}/.env"; h="$(head_of)"; stable code.txt two green >/dev/null; follow
ok "not following: nothing merged" '[ "$(head_of)" = "${h}" ] && grep -q "does not follow" "${T}/out"'
ok "not following: what a reboot left out of a shared network namespace is still healed (DGO-1393)" '[ "$(cat "${STUB}/heals" 2>/dev/null)" = heal ]'

# 2. dgo-stable moved but nothing is green: the office stays where it is
fresh; h="$(head_of)"; stable code.txt two >/dev/null; follow
ok "nothing green: not taken" '[ "$(head_of)" = "${h}" ] && [ "$(notices)" = 0 ]'

# 3. a green commit: taken, one run, pushed to the office's own branch, the take told once; then current
fresh; g="$(stable code.txt two green)"; follow
ok "green: taken, one run, pushed, the take told" 'has "${g}" && [ "$(runs)" = "take " ] && [ "$(origin_of o-dgo)" = "$(head_of)" ] && took_told "${g}"'
ok "green: the take says what came in" 'grep -q "| stable: code.txt | took:test:" "${STUB}/notices"'
ok "green: dgo-stable itself untouched" '[ "$(origin_of dgo-stable)" = "${g}" ]'
follow
ok "then current: no second run, the take not told again" '[ "$(runs)" = "take " ] && [ "$(st LAST_RESULT)" = current ] && took_told "${g}"'

# 3a. the notice centre is down when the take is told: the line waits, and the next cycle tells it — once
fresh; g="$(stable code.txt two green)"; touch "${STUB}/notify.fail"; follow
ok "a take line that cannot be posted waits" 'has "${g}" && [ "$(notices)" = 0 ] && [ "$(st TOLD_PENDING)" = "dgo-stable ${g}" ]'
rm -f "${STUB}/notify.fail"; follow
ok "…and the next cycle tells it, once" 'took_told "${g}" && [ -z "$(st TOLD_PENDING)" ]'
follow
ok "…and never again" 'took_told "${g}"'

# 3b'. a subject is data: quotes, $( ), backticks, a leading dash and long Hebrew reach the line as they are
fresh; said='-n it'"'"'s "quoted" $(touch '"${T}"'/pwned) `touch '"${T}"'/pwned2` — עדכון ארוך מאוד שעובר את המאתיים בתים של שורת הנושא, עם «מירכאות» ומקפים — ועוד קצת עברית כדי שהחיתוך באמצע אות היה נופל כאן בדיוק'
g="$(stable_said code.txt two "${said}")"; follow
ok "a subject with quotes, \$( ), backticks and long Hebrew: told as it is" 'took_told "${g}" && grep -qF -- "| ${said} |" "${STUB}/notices" && [ ! -e "${T}/pwned" ] && [ ! -e "${T}/pwned2" ]'

# 3a'. a take line that waits while a row is open is old news once the row is closed: never said after it
fresh; g="$(stable code.txt two green)"; touch "${STUB}/notify.fail"; follow
printf 'NOTICE=12345\n' >> "${O}/data/follow/state"; rm -f "${STUB}/notify.fail"; follow
ok "a waiting line while a row is open: the row is closed, the line is not said after it" '[ "$(notices)" = 1 ] && grep -q "back to normal" "${STUB}/notices" && [ -z "$(st TOLD_PENDING)" ]'
follow
ok "…nor by a later cycle" '[ "$(notices)" = 1 ] && ! grep -q "המשרד התעדכן" "${STUB}/notices"'

# 3b. an app says it is in use (a meeting): nothing merged, nothing run, nobody told; taken once it is over
fresh; h="$(head_of)"; g="$(stable code.txt two green)"; echo "meet: 1 meeting(s) in progress on the video bridge" > "${STUB}/busy"; follow
ok "busy: not taken, no run, nobody told" '[ "$(head_of)" = "${h}" ] && [ "$(runs)" = "" ] && [ "$(notices)" = 0 ] && grep -q "meeting" <<<"$(st LAST_DETAIL)"'
rm -f "${STUB}/busy"; follow
ok "busy: taken once the meeting is over" 'has "${g}"'

# 3c. what was merged is what runs (DGO-1356): a service whose image is older than its own build files after the take is
# built again — exactly that one; a build that fails is said, and the take stands (merged, healthy, pushed)
fresh; g="$(stable code.txt two green)"; echo web > "${STUB}/old"; follow
ok "old image after a take: built again, exactly that service" 'has "${g}" && [ "$(runs)" = "take rebuild " ] && [ "$(cat "${STUB}/rebuilt")" = "rebuild web" ] && took_told "${g}"'
fresh; g="$(stable code.txt two green)"; echo web > "${STUB}/old"; echo 1 > "${STUB}/rc.rebuild"; follow
ok "a rebuild that fails: said, and the take stands" 'has "${g}" && [ "$(origin_of o-dgo)" = "$(head_of)" ] && grep -q "קוד ישן" "${STUB}/notices"'
ok "a rebuild that fails: its row stays open, no take line closes it" '[ "$(notices)" = 1 ] && grep -q "קוד ישן" <<<"$(tail -1 "${STUB}/notices")"'
fresh; g="$(stable code.txt two green)"; follow
ok "nothing old: no rebuild" '[ "$(runs)" = "take " ] && [ ! -e "${STUB}/rebuilt" ]'

# 4. a newer commit that is NOT green after a green one: only the green one is taken
fresh; g="$(stable code.txt two green)"; n="$(stable other.txt y)"; follow
ok "the newest green, not the newest" 'has "${g}" && ! has "${n}"'

# 4b. the disk floor (DGO-1393: the HP's C: at 100% stopped every build): under the floor nothing is merged and nothing
# runs, and the owner is told once; once there is room the green commit is taken, and what its builds replaced is given back
fresh; h="$(head_of)"; g="$(stable code.txt two green)"; touch "${STUB}/disk.low"; echo 3 > "${STUB}/disk.free"; follow
ok "disk under the floor: not taken, no run, told" \
   '[ "$(head_of)" = "${h}" ] && [ "$(runs)" = "" ] && grep -q "הדיסק כמעט מלא" "${STUB}/notices" && grep -q "3 GiB free" <<<"$(st LAST_DETAIL)"'
follow
ok "disk under the floor: told once" '[ "$(notices)" = 1 ] && [ "$(runs)" = "" ]'
rm -f "${STUB}/disk.low"; follow
ok "room again: taken, and its builds given back" 'has "${g}" && [ "$(runs)" = "take " ] && [ "$(cat "${STUB}/reclaims" 2>/dev/null)" = reclaim ]'
# 4c. …and the disk is never told over a notice already open about something else: the conflict keeps its row
fresh; ( cd "${O}" && printf 'office\n' > code.txt && git commit -qam "office: code" && git push -q origin o-dgo ); h="$(head_of)"
stable code.txt stable green >/dev/null; follow; touch "${STUB}/disk.low"; stable other.txt y green >/dev/null; follow
ok "disk under the floor, a conflict open: its row kept, nothing new told, nothing run" \
   '[ "$(head_of)" = "${h}" ] && [ "$(notices)" = 1 ] && grep -q code.txt "${STUB}/notices" && ! grep -q "הדיסק" "${STUB}/notices" && grep -q "^disk" <<<"$(st LAST_DETAIL)" && [ "$(runs)" = "" ]'

# 5. origin's o-dgo is ahead (pushed from elsewhere): a take of its own, run and checked; dgo-stable the next cycle
fresh; git clone -q -b o-dgo "${T}/origin.git" "${T}/peer"
( cd "${T}/peer" && printf 'p\n' > peer.txt && git add peer.txt && git commit -qm peer && git push -q origin o-dgo ); p="$(git -C "${T}/peer" rev-parse HEAD)"
g="$(stable code.txt two green)"; follow
ok "own branch ahead: taken alone, with a run" 'has "${p}" && ! has "${g}" && [ "$(runs)" = "take " ]'
follow
ok "own branch ahead: dgo-stable the cycle after" 'has "${g}" && [ "$(origin_of o-dgo)" = "$(head_of)" ]'

# 5a. a client office on the public release (DGO-1819): DGO_FOLLOW IS DGO_BRANCH, and it may not push (its push URL
# answers nothing, as GitHub answers a checkout with no credential). origin's new commit is taken, run and checked;
# nothing is pushed back and no «refused push» row is written, cycle after cycle; the owner is told the new version
# (one row of its own — nobody else tells it); with nothing new it is current — no gates to read (none is green
# anywhere here), so never «skipped» into a «fell behind» row; and the next version is taken the same way.
fresh; sed -i 's/^DGO_FOLLOW=.*/DGO_FOLLOW=o-dgo/' "${O}/.env"; git -C "${O}" remote set-url --push origin "${T}/no-right.git"
git clone -q -b o-dgo "${T}/origin.git" "${T}/peer"
( cd "${T}/peer" && printf 'v\n' > version.txt && git add version.txt && git commit -qm "version one" && git push -q origin o-dgo ); p="$(git -C "${T}/peer" rev-parse HEAD)"
follow
ok "public release: origin's new commit taken, with one run" '[ "$(head_of)" = "${p}" ] && [ "$(runs)" = "take " ] && [ "$(st LAST_RESULT)" = took ]'
ok "public release: nothing pushed back, no refused-push row; the version told" \
   '[ -z "$(st PUSH_PENDING)" ] && [ "$(notices)" = 1 ] && grep -q "^info | המשרד התעדכן ל־o-dgo $(git -C "${O}" rev-parse --short "${p}") | version one | took:test:" "${STUB}/notices"'
follow
ok "public release: then current, with no gates to read" '[ "$(st LAST_RESULT)" = current ] && [ "$(runs)" = "take " ] && [ "$(notices)" = 1 ]'
( cd "${T}/peer" && printf 'w\n' > version.txt && git commit -qam "version two" && git push -q origin o-dgo ); p2="$(git -C "${T}/peer" rev-parse HEAD)"
follow
ok "public release: the next version, the same way" '[ "$(head_of)" = "${p2}" ] && [ "$(runs)" = "take take " ] && [ "$(notices)" = 2 ] && [ -z "$(st PUSH_PENDING)" ]'

# 5b. green as git data (gates-hosted's green job): no API to ask, refs/green/dgo-stable on the remote names the commit
fresh; h="$(head_of)"; g="$(stable code.txt two)"; n="$(stable other.txt y)"
DGO_FOLLOW_GREEN_CMD= follow
ok "no green ref and no API: nothing taken, and said" '[ "$(head_of)" = "${h}" ] && grep -q "no green" <<<"$(st LAST_DETAIL)"'
git -C "${T}/origin.git" update-ref refs/green/dgo-stable "${g}"; DGO_FOLLOW_GREEN_CMD= follow
ok "refs/green/dgo-stable read from the remote: its commit taken, the newer one not" 'has "${g}" && ! has "${n}" && [ "$(runs)" = "take " ]'

# 5c. an office with no credential of its own follows THROUGH a linked office's git app (DGO_FOLLOW_VIA): fetched from
# and pushed to the address resolved this cycle; origin itself is never reached. `bbox remote` is played by a stub
# that answers as the real one does — the link's DOOR (registry.link_port 9005) apart from the app's own port (8978) —
# and git's insteadOf maps exactly the door's URL to a local repository, so a URL built from the wrong port fetches
# nothing.
printf '#!/bin/sh\n[ -e "%s/via.down" ] && exit 1\n[ "$1 $2 $3 $4" = "remote peer git-accounts --json" ] || exit 2\necho '"'"'{"office": "peer", "app": {"alias": "git-accounts", "port": 8978}, "registry": {"link_port": 9005}}'"'"'\n' \
  "${STUB}" > "${T}/bin/bbox"; chmod +x "${T}/bin/bbox"
fresh; h="$(head_of)"; g="$(stable code.txt two green)"; git clone -q --mirror "${T}/origin.git" "${T}/via.git"
git -C "${O}" remote set-url origin "${T}/nowhere.git"
git -C "${O}" config "url.${T}/via.git.insteadOf" "http://git-accounts.peer:9005/git/gh/acc/o/r.git"
printf 'DGO_FOLLOW_VIA=peer\n' >> "${O}/.env"; DGO_FOLLOW_BBOX="${T}/bin/bbox" follow
ok "via, without DGO_FOLLOW_VIA_PATH: blocked, nothing fetched, the owner told" \
   '[ "$(head_of)" = "${h}" ] && [ "$(st LAST_RESULT)" = blocked ] && grep -q "DGO_FOLLOW_VIA_PATH" "${STUB}/notices"'
printf 'DGO_FOLLOW_VIA_PATH=/git/gh/acc/o/r.git\n' >> "${O}/.env"; touch "${STUB}/via.down"; DGO_FOLLOW_BBOX="${T}/bin/bbox" follow
ok "via, its git app not published: nothing fetched, and said" '[ "$(head_of)" = "${h}" ] && grep -q "cannot be reached" <<<"$(st LAST_DETAIL)"'
rm -f "${STUB}/via.down"; DGO_FOLLOW_BBOX="${T}/bin/bbox" follow
ok "via: taken from the linked office, at its door, and pushed there" \
   'has "${g}" && [ "$(git -C "${T}/via.git" rev-parse o-dgo)" = "$(head_of)" ] && grep -q "door :9005" "${T}/out"'
ok "via: origin/o-dgo says it was pushed" '[ "$(git -C "${O}" rev-parse origin/o-dgo)" = "$(head_of)" ]'
DGO_FOLLOW_BBOX="${T}/bin/bbox" follow
ok "via: then current" '[ "$(runs)" = "take " ] && [ "$(st LAST_RESULT)" = current ]'
g2="$(stable other.txt z)"; git -C "${T}/via.git" fetch -q "${T}/origin.git" "+refs/heads/dgo-stable:refs/heads/dgo-stable"
git -C "${T}/via.git" update-ref refs/green/dgo-stable "${g2}"; DGO_FOLLOW_GREEN_CMD= DGO_FOLLOW_BBOX="${T}/bin/bbox" follow
ok "via: refs/green/dgo-stable comes through the linked office too" 'has "${g2}" && [ "$(git -C "${T}/via.git" rev-parse o-dgo)" = "$(head_of)" ]'
ok "via: the ref is kept in the follower's own namespace, not as a remote branch" \
   'git -C "${O}" rev-parse -q --verify refs/follow/green/dgo-stable >/dev/null && ! git -C "${O}" rev-parse -q --verify refs/remotes/origin/green/dgo-stable >/dev/null'

# ── health ─────────────────────────────────────────────────────────────────────────────────────────
# 6. a service turns unhealthy: rolled back, run again, never pushed, told once, not retried; a newer green is
fresh; h="$(head_of)"; g="$(stable code.txt two green)"
printf 'web running unhealthy\ndb running -\ninit done -\n' > "${STUB}/health.take"; cp "${STUB}/health" "${STUB}/health.rollback"; follow
ok "unhealthy: rolled back and run again" '[ "$(head_of)" = "${h}" ] && [ "$(cat "${O}/code.txt")" = one ] && [ "$(runs)" = "take rollback " ]'
ok "unhealthy: only the rollback runs as going back on purpose (the deploy ledger lets it)" '[ "$(tr "\n" " " < "${STUB}/allow")" = "take:0 rollback:1 " ]'
ok "unhealthy: the rollback is never refused for the disk (admitted), the take asked like any job" '[ "$(tr "\n" " " < "${STUB}/admitted")" = "take:unset rollback:1 " ]'
ok "unhealthy: origin/o-dgo untouched" '[ "$(origin_of o-dgo)" = "${h}" ]'
ok "unhealthy: told once, with the service, healthy again" '[ "$(notices)" = 1 ] && grep -q "web running unhealthy" "${STUB}/notices" && grep -q "healthy again" "${STUB}/notices"'
DGO_FOLLOW_STALE_S=0 follow
ok "unhealthy: the same commit waits, no new run or notice, no stale alarm" '[ "$(head_of)" = "${h}" ] && [ "$(runs)" = "take rollback " ] && [ "$(notices)" = 1 ] && [ "$(st LAST_RESULT)" = waiting ]'
rm -f "${STUB}/health.take"; g2="$(stable code.txt three green)"; follow
ok "a newer green after a failure: taken, the row closed" 'has "${g2}" && grep -q "^info" <<<"$(tail -1 "${STUB}/notices")"'
ok "a take that closes the row: its «back to normal» says it, nothing more" '! grep -q "המשרד התעדכן" "${STUB}/notices" && grep -q "back to normal: dgo-stable [0-9a-f]* taken" <<<"$(tail -1 "${STUB}/notices")"'

# 7. a service vanishes (the merge removed or disabled it): rolled back
fresh; h="$(head_of)"; stable code.txt two green >/dev/null; printf 'web running healthy\ninit done -\n' > "${STUB}/health.take"
cp "${STUB}/health" "${STUB}/health.rollback"; follow
ok "a vanished service: rolled back, named" '[ "$(head_of)" = "${h}" ] && grep -q "db gone" "${STUB}/notices"'
# …but one the take RETIRED (its compose key removed by the take, and gone from the compiled model) is a release
fresh; git clone -q -b dgo-stable "${T}/origin.git" "${T}/side"
( cd "${T}/side" && sed -i '/^  db:$/,+1d' apps/x/docker-compose.yml && git commit -qam "stable: retire db" && git push -q origin dgo-stable )
g="$(git -C "${T}/side" rev-parse HEAD)"; echo "${g}" >> "${STUB}/green"
printf 'web running healthy\ninit done -\n' > "${STUB}/health.take"; printf 'printf "web\\\\ninit\\\\n" > "${STUB}/model"\n' > "${STUB}/do.take"; follow
ok "a retired service: taken" 'has "${g}" && took_told "${g}"'
# …while one that only dropped out of the model (the take did not remove it: a compiler or app.json gone wrong) is not
fresh; h="$(head_of)"; stable code.txt two green >/dev/null; printf 'web running healthy\ninit done -\n' > "${STUB}/health.take"
printf 'printf "web\\\\ninit\\\\n" > "${STUB}/model"\n' > "${STUB}/do.take"; cp "${STUB}/health" "${STUB}/health.rollback"; follow
ok "dropped from the model by accident: rolled back" '[ "$(head_of)" = "${h}" ] && grep -q "db gone" "${STUB}/notices"'
# …a service that was good before only by leaning on one that was not (depends_on: the Dell's n8n sidecars beside an
# exited n8n, 2026-11-11) falls after the take: not the take's — taken, and its fall is not a rollback
fresh; g="$(stable code.txt two green)"
printf 'web running healthy\ndb running -\ninit done -\nbroker exited -\nside running healthy\nside2 running healthy\n' > "${STUB}/health"
printf 'web running healthy\ndb running -\ninit done -\nbroker exited -\nside exited -\nside2 exited -\n' > "${STUB}/health.take"
printf 'web\ndb\ninit\nbroker\nside\nside2\n' > "${STUB}/model"; printf 'side broker\nside2 side\n' > "${STUB}/deps"; follow
ok "a service good before only on a dead dependency (and one on IT): its fall is not the take's — taken" 'has "${g}" && took_told "${g}"'
ok "…and each spared fall is named in the cycle's log, with what it leaned on" \
   'grep -q "side exited - — not the take.s: it leaned on broker" "${T}/out" && grep -q "side2 exited - — not the take.s: it leaned on broker" "${T}/out"'
ok "…and in the follow's own log, the file every notice points at" 'grep -q "spared: side exited - — leaned on broker" "${O}/data/follow/log"'
# …but a dependency the take PUT RIGHT spares nothing: the dependent's fall is then the take's — rolled back
fresh; h="$(head_of)"; stable code.txt two green >/dev/null
printf 'web running healthy\ndb running -\ninit done -\nbroker exited -\nside running healthy\n' > "${STUB}/health"
printf 'web running healthy\ndb running -\ninit done -\nbroker running healthy\nside exited -\n' > "${STUB}/health.take"
printf 'web\ndb\ninit\nbroker\nside\n' > "${STUB}/model"; printf 'side broker\n' > "${STUB}/deps"; cp "${STUB}/health" "${STUB}/health.rollback"; follow
ok "the dependency good after, the dependent fallen: rolled back" '[ "$(head_of)" = "${h}" ] && grep -q "side exited" "${STUB}/notices"'
# …and a leaning service that VANISHED is judged as ever (a dead dependency never makes one gone) — rolled back
fresh; h="$(head_of)"; stable code.txt two green >/dev/null
printf 'web running healthy\ndb running -\ninit done -\nbroker exited -\nside running healthy\n' > "${STUB}/health"
printf 'web running healthy\ndb running -\ninit done -\nbroker exited -\n' > "${STUB}/health.take"
printf 'web\ndb\ninit\nbroker\nside\n' > "${STUB}/model"; printf 'side broker\n' > "${STUB}/deps"; cp "${STUB}/health" "${STUB}/health.rollback"; follow
ok "a leaning service that vanished: rolled back, named gone" '[ "$(head_of)" = "${h}" ] && grep -q "side gone" "${STUB}/notices"'
# …and after a rollback (for another service), the report of what is still down spares nothing: a leaning sidecar
# that is down is said, never «healthy again» over it
fresh; h="$(head_of)"; stable code.txt two green >/dev/null
printf 'web running healthy\ndb running -\ninit done -\nbroker exited -\nside running healthy\n' > "${STUB}/health"
printf 'web running unhealthy\ndb running -\ninit done -\nbroker exited -\nside exited -\n' > "${STUB}/health.take"
printf 'web running healthy\ndb running -\ninit done -\nbroker exited -\nside exited -\n' > "${STUB}/health.rollback"
printf 'web\ndb\ninit\nbroker\nside\n' > "${STUB}/model"; printf 'side broker\n' > "${STUB}/deps"; follow
ok "rolled back for web: the report names the leaning sidecar still down, not «healthy again»" \
   '[ "$(head_of)" = "${h}" ] && grep -q "side exited" "${STUB}/notices" && ! grep -q "healthy again" "${STUB}/notices"'
# …while the very same fall with no broken dependency under it is the take's: rolled back
fresh; h="$(head_of)"; stable code.txt two green >/dev/null
printf 'web running healthy\ndb running -\ninit done -\nbroker exited -\nside running healthy\n' > "${STUB}/health"
printf 'web running healthy\ndb running -\ninit done -\nbroker exited -\nside exited -\n' > "${STUB}/health.take"
printf 'web\ndb\ninit\nbroker\nside\n' > "${STUB}/model"; printf 'side web\n' > "${STUB}/deps"; cp "${STUB}/health" "${STUB}/health.rollback"; follow
ok "the same fall on a dependency that was good: rolled back, named" '[ "$(head_of)" = "${h}" ] && grep -q "side exited" "${STUB}/notices"'

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

# 12a. LEFT WORK (DGO-1782: the HP stopped updating itself on 11-04, behind files staged on 11-03 and changed by sessions
# that died). A file untouched for DGO_FOLLOW_KEEP_AFTER is left work; a recent one is still refused (10, 12).
old() { touch -d "@$(( $(date +%s) - 7200 ))" "${O}/$1"; }
# …staged, and the target does not touch it: unstaged, its text stays, taken
fresh; g="$(stable code.txt two green)"; printf 'z\n' > "${O}/staged.txt"; git -C "${O}" add staged.txt; old staged.txt
DGO_FOLLOW_KEEP_AFTER=3600 follow
ok "left staged work: unstaged, its text kept, taken" 'has "${g}" && [ "$(cat "${O}/staged.txt")" = z ] && git -C "${O}" diff --cached --quiet && ! git -C "${O}" log --format=%s | grep -q "work left"'
# …changed in a file the target changes too, merging cleanly: kept in a commit of its own, taken, both changes there, told
fresh; stable lines.txt "$(printf 'a\nb\nc')" green >/dev/null; follow
g="$(stable lines.txt "$(printf 'A\nb\nc')" green)"; printf 'a\nb\nC\n' > "${O}/lines.txt"; old lines.txt
DGO_FOLLOW_KEEP_AFTER=3600 follow
ok "left work in a file the target changes: kept in a commit, taken, both changes in" 'has "${g}" && [ "$(tr "\n" " " < "${O}/lines.txt")" = "A b C " ] && git -C "${O}" log --format=%s | grep -q "work left uncommitted on test" && [ -z "$(git -C "${O}" diff --name-only HEAD)" ]'
ok "…and the owner told where it was kept" 'grep -q "שמרתי עבודה שנשארה לא מקומטת" "${STUB}/notices" && grep -q "kept:test:" "${STUB}/notices"'
ok "…and the kept commit reached the office branch with the take" '[ "$(origin_of o-dgo)" = "$(head_of)" ] && git -C "${T}/origin.git" log --format=%s o-dgo | grep -q "work left uncommitted"'
# …conflicting with the target: kept, the take refused as any conflict, the work intact in the commit, told
fresh; h="$(head_of)"; g="$(stable code.txt two green)"; printf 'mine\n' > "${O}/code.txt"; old code.txt
DGO_FOLLOW_KEEP_AFTER=3600 follow
ok "left work that conflicts: kept in a commit, not merged, a failed target, told" '! has "${g}" && [ "$(git -C "${O}" show HEAD:code.txt)" = mine ] && [ "$(cat "${O}/code.txt")" = mine ] && [ "$(st FAILED_TARGET)" = "${g}" ] && [ ! -e "$(git -C "${O}" rev-parse --absolute-git-dir)/MERGE_HEAD" ]'
# …a recent change whose text the target already holds (carried by content): not a session's work — kept and taken
fresh; g="$(stable code.txt two green)"; printf 'two\n' > "${O}/code.txt"
DGO_FOLLOW_KEEP_AFTER=3600 follow
ok "a recent change the target already carries: kept, taken" 'has "${g}" && [ "$(cat "${O}/code.txt")" = two ] && [ -z "$(git -C "${O}" diff --name-only HEAD)" ]'
# …a recent change holding an EARLIER text of the target is not carried: refused, as a session's work (second reader)
fresh; stable code.txt v1 green >/dev/null; follow; g="$(stable code.txt v2 green)"; printf 'one\n' > "${O}/code.txt"; h="$(head_of)"
DGO_FOLLOW_KEEP_AFTER=3600 follow
ok "a recent change holding an earlier text of the target: refused, not kept" '[ "$(head_of)" = "${h}" ] && [ "$(cat "${O}/code.txt")" = one ] && ! git -C "${O}" log --format=%s | grep -q "work left"'
# …a file a session staged while the take waited stays out of the kept commit, and stays staged
fresh; g="$(stable code.txt two green)"; printf 'mine\n' > "${O}/code.txt"; old code.txt
printf '#!/bin/sh\nprintf "late\\n" > "%s/late.txt"; git -C "%s" add late.txt; exec "%s" "$@"\n' "${O}" "${O}" "${T}/bin/health" > "${T}/bin/health-late"
chmod +x "${T}/bin/health-late"
DGO_FOLLOW_KEEP_AFTER=3600 DGO_FOLLOW_HEALTH_CMD="${T}/bin/health-late" follow
ok "something staged during the wait is not in the kept commit" 'k="$(git -C "${O}" log --format=%H --grep="work left" -n 1)" && [ -n "${k}" ] && ! git -C "${O}" show --name-only --format= "${k}" | grep -q late.txt'
# …a deleted file is a session's call: refused, not kept
fresh; h="$(head_of)"; g="$(stable code.txt two green)"; rm -f "${O}/code.txt"
DGO_FOLLOW_KEEP_AFTER=0 follow
ok "a deleted file the target changes: refused, not kept" '[ "$(head_of)" = "${h}" ] && [ ! -e "${O}/code.txt" ] && grep -q "code.txt" "${STUB}/notices"'
# …a dry run says what it would keep, and keeps nothing
fresh; h="$(head_of)"; g="$(stable code.txt two green)"; printf 'mine\n' > "${O}/code.txt"; old code.txt
DGO_FOLLOW_KEEP_AFTER=3600 follow --dry-run
ok "dry run: says it would keep, keeps nothing" '[ "$(head_of)" = "${h}" ] && grep -q "would keep left work" "${T}/out" && [ -n "$(git -C "${O}" diff --name-only HEAD)" ]'

# 13. a file the target adds is already here (an ignored file the office keeps): refused, the file intact
fresh; h="$(head_of)"; stable keep.local tracked green >/dev/null; printf 'office data\n' > "${O}/keep.local"; follow
ok "an existing file where the target adds one: kept, not merged" '[ "$(head_of)" = "${h}" ] && [ "$(cat "${O}/keep.local")" = "office data" ] && [ -z "$(st FAILED_TARGET)" ]'
# …but a file the office already TRACKS (a cherry-pick of the same commit) is no obstacle
fresh; g="$(stable added.txt same green)"
( cd "${O}" && git fetch -q origin dgo-stable && git cherry-pick -x "${g}" >/dev/null && git push -q origin o-dgo ); follow
ok "a file already tracked through a cherry-pick: taken" 'has "${g}" && took_told "${g}"'

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
# 16a. …the same target again with the branch unchanged: waits. Once the office resolves it on its branch: taken (DGO-1299)
fresh; ( cd "${O}" && printf 'office\n' > code.txt && git commit -qam "office: code" && git push -q origin o-dgo ); h="$(head_of)"
g="$(stable code.txt stable green)"; follow; follow
ok "conflict, branch unchanged: waits" '[ "$(head_of)" = "${h}" ] && tail -1 "${O}/data/follow/log" | grep -q "waiting for a newer one"'
( cd "${O}" && printf 'stable\n' > code.txt && git commit -qam "office: take stable's code" ); follow
ok "conflict, branch moved: tried again and taken" 'grep -q "trying it again" "${T}/out" && has "${g}" && [ "$(st LAST_RESULT)" = took ] && [ "$(origin_of o-dgo)" = "$(head_of)" ]'
# …and an old state (a failed target, no FAILED_HEAD: not known to be a conflict) still waits when the branch moves
printf 'FAILED_TARGET=%s\nFAILED_AT=x\n' "$(stable code.txt newer green)" > "${O}/data/follow/state"
( cd "${O}" && printf 'y\n' > other.txt && git commit -qam "office: other" ); h="$(head_of)"; follow
ok "failed without FAILED_HEAD, branch moved: still waits" '[ "$(head_of)" = "${h}" ] && tail -1 "${O}/data/follow/log" | grep -q "waiting for a newer one"'

# 16b. content dgo-stable itself carried into the office BY CONTENT (a cherry-pick, the release line carrying a branch),
#      then changed again on dgo-stable: the merge base never moved, so the files conflict (add/add, modify/modify) —
#      but the office's versions are ones dgo-stable had, so dgo-stable's are taken (vps1-dgo, 2026-11-03)
fresh; c1="$(stable carried.txt v1)"; c2="$(stable code.txt two)"
( cd "${O}" && git fetch -q origin dgo-stable && git show "${c1}:carried.txt" > carried.txt && git show "${c2}:code.txt" > code.txt \
  && git add carried.txt code.txt && git commit -qm "office: dgo-stable's files, by content" && git push -q origin o-dgo )
stable code.txt three >/dev/null; g="$(stable carried.txt v2 green)"; follow
ok "carried content: taken, dgo-stable's versions win, the take told" 'has "${g}" && [ "$(cat "${O}/carried.txt")" = v2 ] && [ "$(cat "${O}/code.txt")" = three ] && took_told "${g}" && [ "$(origin_of o-dgo)" = "$(head_of)" ]'
ok "carried content: the merge says what it took" 'grep -q "carried, its versions taken: carried.txt code.txt" <<<"$(git -C "${O}" log -1 --format=%s)"'
# …but a path among them that the office DID change itself (a version dgo-stable never had) stops the take, as before
fresh; c1="$(stable carried.txt v1)"
( cd "${O}" && git fetch -q origin dgo-stable && git show "${c1}:carried.txt" > carried.txt && printf 'office\n' > other.txt \
  && git add carried.txt other.txt && git commit -qm "office: carried + its own" && git push -q origin o-dgo ); h="$(head_of)"
stable other.txt stable >/dev/null; stable carried.txt v2 green >/dev/null; follow
ok "carried and own together: stopped, nothing taken, told the files" '[ "$(head_of)" = "${h}" ] && [ ! -e "${O}/.git/MERGE_HEAD" ] && [ "$(cat "${O}/other.txt")" = office ] && grep -q other.txt "${STUB}/notices"'
# …and when the commit that holds the office's version sits on a MERGE's second side: the release line puts a batch on
# dgo-stable through another line's merge of it (batch 34: first parent the Mac's merge of c89acf4f), and that merge
# equals its first parent for the path, so git's default history drops the side that carried it — vps1-dgo stopped on
# two files dgo-stable had carried (2026-11-10)
fresh
( cd "${O}" && printf 'o1\n' > carried.txt && git add carried.txt && git commit -qm "office: its own text" && git push -q origin o-dgo )
stable carried.txt o1 >/dev/null; s2="$(stable carried.txt v2)"
( cd "${T}/side" && git checkout -q -b mac "$(git rev-list --max-parents=0 HEAD)" && printf 'v2\n' > carried.txt \
  && git add carried.txt && git commit -qm "mac: the merged text" && git merge -q --no-ff --no-edit "${s2}" \
  && git push -q origin mac:dgo-stable )
g="$(git -C "${T}/side" rev-parse mac)"; printf '%s\n' "${g}" >> "${STUB}/green"
holder() { ( cd "${O}" && git fetch -q origin dgo-stable && git log "$@" --format=%H "HEAD..origin/dgo-stable" -- carried.txt \
  | while read -r c; do [ "$(git show "${c}:carried.txt")" = o1 ] && echo "${c}"; done ); }
ok "carried behind a merge: git's default history hides the holder, the full history finds it" '[ -z "$(holder)" ] && [ -n "$(holder --full-history)" ]'
follow
ok "carried behind a merge: taken, dgo-stable's version wins, pushed and told" 'has "${g}" && [ "$(cat "${O}/carried.txt")" = v2 ] && grep -q "carried, its versions taken: carried.txt" <<<"$(git -C "${O}" log -1 --format=%s)" && [ "$(origin_of o-dgo)" = "$(head_of)" ] && took_told "${g}"'
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

# 18a. …a take of the office's OWN branch killed the same way (all a client office on the public release ever takes,
# DGO-1819): origin already holds that commit — no proof it was verified — so it is rolled back the same way, never
# «pushed by an earlier cycle»
fresh; sed -i 's/^DGO_FOLLOW=.*/DGO_FOLLOW=o-dgo/' "${O}/.env"; git -C "${O}" remote set-url --push origin "${T}/no-right.git"; h="$(head_of)"
git clone -q -b o-dgo "${T}/origin.git" "${T}/peer"
( cd "${T}/peer" && printf 'v\n' > version.txt && git add version.txt && git commit -qm version && git push -q origin o-dgo ); p="$(git -C "${T}/peer" rev-parse HEAD)"
printf 'pkill -KILL -f "%s/dgo-follow\\\\."\n' "${TMPDIR}" > "${STUB}/do.take"; follow; rm -f "${STUB}/do.take"
ok "own branch killed mid-take: left merged" '[ "$(head_of)" = "${p}" ]'
follow
ok "own branch killed mid-take: the next cycle rolls it back, never «verified by an earlier cycle»" \
   '[ "$(head_of)" = "${h}" ] && [ "$(st FAILED_TARGET)" = "${p}" ] && grep -q "stopped before its health check" "${STUB}/notices"'
# 18b. a VERIFIED dgo-stable take killed in its push (the hook kills the cycle and refuses): the next cycle keeps the
# take and marks its push pending — never «pushed» while origin lacks it — and the cycle after pushes it
fresh; h="$(head_of)"; g="$(stable code.txt two green)"
printf '#!/bin/sh\npkill -KILL -f "%s/dgo-follow\\\\."\nexit 1\n' "${TMPDIR}" > "${T}/origin.git/hooks/pre-receive"
chmod +x "${T}/origin.git/hooks/pre-receive"; follow; rm -f "${T}/origin.git/hooks/pre-receive"
ok "killed in the push: merged, healthy, not on origin" 'has "${g}" && [ "$(origin_of o-dgo)" = "${h}" ] && [ -n "$(st TAKING)" ]'
follow
ok "killed in the push: the next cycle keeps it, its push pending" \
   'has "${g}" && [ -z "$(st TAKING)" ] && [ "$(st PUSH_PENDING)" = "$(head_of)" ] && [ "$(st LAST_RESULT)" = took ]'
follow
ok "killed in the push: the cycle after pushes it" '[ "$(origin_of o-dgo)" = "$(head_of)" ] && [ -z "$(st PUSH_PENDING)" ]'

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
ok "push refused: taken, told, pending" 'has "${g}" && [ "$(origin_of o-dgo)" != "$(head_of)" ] && [ "$(st PUSH_PENDING)" = "$(head_of)" ] && [ "$(notices)" = 1 ] && ! grep -q "המשרד התעדכן" "${STUB}/notices"'
rm -f "${STUB}/reject"; follow
ok "push refused: pushed by the next cycle, the row closed" '[ "$(origin_of o-dgo)" = "$(head_of)" ] && grep -q "^info" <<<"$(tail -1 "${STUB}/notices")" && ! grep -q "המשרד התעדכן" "${STUB}/notices"'

# ── the rest ───────────────────────────────────────────────────────────────────────────────────────
# 21. --dry-run: says what it would do, writes nothing
fresh; h="$(head_of)"; stable code.txt two green >/dev/null; follow --dry-run
ok "dry run: nothing merged, run, written or told" '[ "$(head_of)" = "${h}" ] && [ "$(runs)" = "" ] && [ ! -e "${O}/data/follow/state" ] && [ "$(notices)" = 0 ] && grep -q "would take" "${T}/out"'
ok "dry run: nothing healed" '[ ! -e "${STUB}/heals" ]'
# 21b. a heavy job holds the slot: the cycle is put off, and nothing is healed under it (that job's own `up` rejoins)
fresh; mkdir -p "${O}/data/.locks"; ( flock "${O}/data/.locks/heavy" sleep 20 ) & hp=$!; sleep 1; follow
ok "a heavy job holds the slot: put off, nothing healed under it" '[ ! -e "${STUB}/heals" ] && grep -q "heavy job holds the slot" <<<"$(st LAST_DETAIL)"'
kill "${hp}" 2>/dev/null; wait "${hp}" 2>/dev/null
# 21c. `bbox follow heal` (the boot timer at 3 and 8 minutes; the runner's first minutes): the heal and nothing after
#      it, never under a heavy job, never beside a cycle (DGO-1393)
fresh; b="$(git -C "${O}" rev-parse refs/remotes/origin/dgo-stable)"; h="$(head_of)"; stable code.txt two green >/dev/null; follow heal
ok "follow heal: healed; nothing fetched, merged, run or recorded" \
   '[ "$(cat "${STUB}/heals" 2>/dev/null)" = heal ] && [ "$(git -C "${O}" rev-parse refs/remotes/origin/dgo-stable)" = "${b}" ] && [ "$(head_of)" = "${h}" ] && [ "$(runs)" = "" ] && [ ! -e "${O}/data/follow/state" ]'
fresh; mkdir -p "${O}/data/.locks"; ( flock "${O}/data/.locks/heavy" sleep 20 ) & hp=$!; sleep 1; follow heal; rc=$?
ok "follow heal under a heavy job: nothing healed, and it says so (not every heavy job runs an up)" \
   '[ "${rc}" = 0 ] && [ ! -e "${STUB}/heals" ] && grep -q "the heal is put off" "${T}/out"'
kill "${hp}" 2>/dev/null; wait "${hp}" 2>/dev/null
fresh; mkdir -p "${O}/data/.locks"; flock "${O}/data/.locks/follow" sleep 5 & sleep 0.5; follow heal; wait
ok "follow heal beside a cycle: leaves at once, nothing healed (the cycle healed first)" 'grep -q "another follow cycle is running" "${T}/out" && [ ! -e "${STUB}/heals" ]'

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

# 26. the load ceiling: declared in .env (quoted, with a comment) it holds; a ceiling below any load skips; not a
# number → the CPU count, said (DGO-1299: the HP sat above its 6 CPUs all day and never took a green dgo-stable)
fresh; stable code.txt two green >/dev/null
printf 'DGO_FOLLOW_MAX_LOAD="100000"  # the HP\n' >> "${O}/.env"; DGO_FOLLOW_MAX_LOAD= follow
ok "load ceiling from .env: taken" '[ "$(cat "${O}/code.txt")" = two ]'
fresh; stable code.txt two green >/dev/null; h="$(head_of)"
printf 'DGO_FOLLOW_MAX_LOAD=0\n' >> "${O}/.env"; DGO_FOLLOW_MAX_LOAD= follow
ok "load ceiling 0 from .env: skipped" '[ "$(head_of)" = "${h}" ] && grep -q "skipped load" "${O}/data/follow/log"'
fresh; printf 'DGO_FOLLOW_MAX_LOAD=abc\n' >> "${O}/.env"; DGO_FOLLOW_MAX_LOAD= follow
ok "load ceiling not a number: said" 'grep -q "is not a number" "${T}/out"'

echo
[ "${fails}" = 0 ] && echo "test_follow: all passed" || echo "test_follow: ${fails} FAILED"
exit $((fails > 0))
