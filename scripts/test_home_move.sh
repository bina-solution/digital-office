#!/usr/bin/env bash
# test_home_move — scripts/home-move.sh on a throwaway office folder (DGO-2019). Needs root (the move keeps every
# owner); anywhere else it runs itself in a throwaway container:   bash scripts/test_home_move.sh
# The engine is a stub (DGO_HOME_MOVE_DC) that writes what it was asked into a log, and fails a run where told to.
# What it holds:
#   * a folder that holds databases is not moved; a non-empty target, a target or a C: without room are refused;
#   * a dry run stops, copies and writes nothing;
#   * the move stops the office, copies every file with its owner and mode, pins the old compose project in the new
#     .env, repairs only the new folder's worktrees, carries Claude Desktop's memory, runs the office from the new
#     folder — and only then marks the old one (MOVED-TO.txt) and makes the Desktop shortcut;
#   * a copy that differs, or a run in the new folder that fails, brings the office back where it was: exactly the
#     containers that ran, the partial copy removed, nothing marked.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$(id -u)" != 0 ]; then
  # the follow runner's image: bash, python3, git and GNU tar, as the host the move runs on has
  exec docker run --rm --network none -v "${HERE}:/src-scripts:ro" -v "${HERE}/../bbox.cmd:/src-bbox.cmd:ro" \
    --entrypoint bash "${DGO_TEST_IMAGE:-mydgo-follow-runner:latest}" /src-scripts/test_home_move.sh
fi
SRC_SCRIPTS="${HERE}"
BBOX_CMD="${DGO_TEST_BBOX_CMD:-/src-bbox.cmd}"
T="$(mktemp -d)"; fail=0
ok()  { echo "  ok  $*"; }
bad() { echo "  FAIL $*"; fail=1; }
cat > "${T}/stub.sh" <<EOF
#!/bin/sh
# the engine, stubbed: every verb is logged; \`running\` names two containers; a run fails where STUB_FAIL_IN says
echo "\$*" >> "${T}/log"
rc=0
case "\$1" in
  running) echo "c1 c2" ;;
  run-in)  echo "  hold=\${DGO_DATA_HOLD:-} admitted=\${BBOX_DISK_ADMITTED:-}" >> "${T}/log"
           [ "\$2" != "\${STUB_FAIL_IN:-}" ] || rc=1
           [ -z "\${STUB_FAIL_ALL:-}" ] || rc=1 ;;
  follow-busy) [ -n "\${STUB_FOLLOW_BUSY:-}" ] || rc=1 ;;
esac
# a cut (a reboot's TERM) at the verb STUB_TERM_AT names: the move itself is signalled
[ "\$1" != "\${STUB_TERM_AT:-}" ] || kill -TERM "\${PPID}"
exit \${rc}
EOF
chmod +x "${T}/stub.sh"
export DGO_HOME_MOVE_DC="${T}/stub.sh"
office_tree() {   # a throwaway office: the move's scripts, a git repository with a worktree, .env, data/ of another owner
  local d="$1"; mkdir -p "$d/scripts" "$d/data/app"
  cp "${SRC_SCRIPTS}/home-move.sh" "${SRC_SCRIPTS}/lib.sh" "$d/scripts/"
  printf '#!/bin/sh\nexit 0\n' > "$d/bbox"; chmod +x "$d/bbox"
  printf 'DEPLOYMENT_NAME=test\nBUSINESS_NAME=t\n' > "$d/.env"
  echo state > "$d/data/app/db"; chown -R 999:999 "$d/data/app"; chmod 700 "$d/data/app"
  ln -s data/app "$d/link"
  ( cd "$d" && git init -q && git -c user.name=t -c user.email=t@t commit -q --allow-empty -m init \
      && git worktree add -q "$d/wt1" -b wt1 ) >/dev/null 2>&1
}
mv_() { ( cd "${T}/old" && bash scripts/home-move.sh "$@" ) > "${T}/out" 2>&1; }
office_tree "${T}/old"
oldproj="$(basename "${T}" | tr '[:upper:]' '[:lower:]')"

DGO_HOME_MOVE_TEST_FS=ext4 mv_ move --to "${T}/new" && bad "a folder on ext4 moved" || ok "a folder that holds databases is not moved"
export DGO_HOME_MOVE_TEST_FS=9p
mkdir -p "${T}/full"; touch "${T}/full/x"
mv_ move --to "${T}/full" && bad "moved over a non-empty folder" || ok "a non-empty target is refused"
DGO_HOME_MOVE_CFREE_KB=100 mv_ move --to "${T}/new" && bad "moved with C: full" || true
grep -q "C: has" "${T}/out" && [ ! -e "${T}/new" ] && ok "a C: without room is refused (WSL's disk grows on it)" \
  || bad "C: full: $(tail -2 "${T}/out")"
: > "${T}/log"
mv_ move --to "${T}/new" --dry-run && [ ! -e "${T}/new" ] && ! grep -q stop "${T}/log" \
  && ok "a dry run stops, copies and writes nothing" || bad "dry run: $(cat "${T}/out")"
STUB_FOLLOW_BUSY=1 mv_ move --to "${T}/new" && bad "moved during a follow cycle" || true
grep -q "follow cycle is running" "${T}/out" && ! grep -q '^stop' "${T}/log" \
  && ok "a follow cycle under way: the move waits for it, nothing stopped" || bad "follow busy: $(tail -2 "${T}/out")"
mv_ move --to "${T}/n!ew" && bad "a target cmd.exe would mangle was taken" || true
grep -q "letters, digits" "${T}/out" && ok "a target name cmd.exe would mangle is refused" || bad "ascii: $(tail -1 "${T}/out")"

: > "${T}/log"
mv_ move --to "${T}/new"; rc=$?
[ "${rc}" = 0 ] && ok "the move ran" || bad "the move: rc=${rc} $(tail -3 "${T}/out")"
[ "$(grep -vE '^(follow-busy|timers)' "${T}/log" | head -2 | tr '\n' ' ')" = "running stop " ] \
  && [ "$(grep -nE '^(timers stop|stop)$' "${T}/log" | head -1 | cut -d: -f2)" = "timers stop" ] \
  && ok "the office was listed, the follow timers stopped, then the office" \
  || bad "order: $(cat "${T}/log")"
[ "$(stat -c '%u %a' "${T}/new/data/app")" = "999 700" ] && [ "$(cat "${T}/new/data/app/db")" = state ] \
  && ok "data/ copied with its owner and mode" || bad "owner/mode: $(stat -c '%u %a' "${T}/new/data/app")"
[ -L "${T}/new/link" ] && [ -d "${T}/new/.git" ] && ok ".git, .env and links copied" || bad "copy incomplete"
grep -qx "COMPOSE_PROJECT_NAME=old" "${T}/new/.env" && ! grep -q COMPOSE_PROJECT_NAME "${T}/old/.env" \
  && ok "the new folder's .env pins the project the old folder ran under (old)" || bad "project: $(cat "${T}/new/.env")"
[ "$(cat "${T}/new/.git/worktrees/wt1/gitdir")" = "${T}/new/wt1/.git" ] \
  && [ "$(cat "${T}/new/wt1/.git")" = "gitdir: ${T}/new/.git/worktrees/wt1" ] \
  && [ "$(cat "${T}/old/.git/worktrees/wt1/gitdir")" = "${T}/old/wt1/.git" ] \
  && [ "$(cat "${T}/old/wt1/.git")" = "gitdir: ${T}/old/.git/worktrees/wt1" ] \
  && [ "$(git -C "${T}/new/wt1" rev-parse --git-common-dir)" = "${T}/new/.git" ] \
  && ok "the new folder's worktree is the new repository's, both ways; the old folder's is untouched" \
  || bad "worktrees: new=$(cat "${T}/new/.git/worktrees/wt1/gitdir") / $(cat "${T}/new/wt1/.git") old=$(cat "${T}/old/.git/worktrees/wt1/gitdir")"
grep -qF "claude-memory $(printf '%s' "${T}/old" | sed 's/[^A-Za-z0-9]/-/g') $(printf '%s' "${T}/new" | sed 's/[^A-Za-z0-9]/-/g')" "${T}/log" \
  && ok "Claude Desktop's memory of the folder follows it (its key: every non-alphanumeric a -)" \
  || bad "memory: $(grep claude "${T}/log")"
grep -A1 "^run-in ${T}/new" "${T}/log" | grep -q "hold=1" \
  && ok "the move's own run keeps every store on its volume (DGO_DATA_HOLD)" || bad "hold: $(cat "${T}/log")"
! grep -q "^keepalive" "${T}/log" \
  && ok "the Windows keepalive stays with its script on C: (never read from the disk it watches)" \
  || bad "keepalive re-installed: $(cat "${T}/log")"
[ ! -e "${T}/new/.dgo-home-move-partial" ] && ok "a finished move leaves no partial mark" || bad "partial mark left"
n_run="$(grep -n "^run-in ${T}/new" "${T}/log" | cut -d: -f1)"; n_lnk="$(grep -n '^desktop-shortcut' "${T}/log" | cut -d: -f1)"
[ -n "${n_run}" ] && [ -n "${n_lnk}" ] && [ "${n_run}" -lt "${n_lnk}" ] \
  && ok "the office ran from the new folder, and only then came the Desktop shortcut" || bad "run/shortcut: $(cat "${T}/log")"
head -1 "${T}/old/MOVED-TO.txt" | grep -qx "${T}/new" && ok "the old folder says where the office went" \
  || bad "old folder not marked"
grep -q 'MOVED-TO.txt' "${BBOX_CMD}" && grep -q 'if exist' "${BBOX_CMD}" \
  && ok "bbox.cmd hands over by reading MOVED-TO.txt, to a folder that is there" || bad "bbox.cmd: no MOVED-TO.txt hand-over in ${BBOX_CMD}"
[ -f "${T}/old/data/app/db" ] && ok "the old folder is kept as it was" || bad "old data gone"
mv_ move --to "${T}/again" && bad "a moved folder moved again" || true
grep -q "was moved already" "${T}/out" && [ ! -e "${T}/again" ] && ok "a folder already moved is never moved again" \
  || bad "moved twice: $(tail -2 "${T}/out")"

# a move cut by a reboot's TERM after the stop: what ran starts again, the copy is removed, nothing marked
rm -rf "${T}/old" "${T}/new"; office_tree "${T}/old"; : > "${T}/log"
STUB_TERM_AT=claude-memory mv_ move --to "${T}/new" && bad "a cut move went on" || true
grep -qx "start-these c1 c2" "${T}/log" && [ ! -e "${T}/new" ] && [ ! -f "${T}/old/MOVED-TO.txt" ] \
  && ok "a move cut after the stop: exactly what ran starts again, the copy removed, nothing marked" \
  || bad "cut: $(cat "${T}/log") $(tail -3 "${T}/out")"
# …and a copy a cut left behind (its partial mark) is set aside by the next move, never moved over
mkdir -p "${T}/new"; touch "${T}/new/.dgo-home-move-partial" "${T}/new/x"; : > "${T}/log"
mv_ move --to "${T}/new"
ls -d "${T}"/new.failed-* >/dev/null 2>&1 && head -1 "${T}/old/MOVED-TO.txt" | grep -qx "${T}/new" \
  && ok "a partial copy left by a cut move is set aside, and the move goes on" || bad "partial: $(tail -3 "${T}/out")"

# C: will not take the mark — nothing written, or a truncated file left: the office goes back to the old folder,
# which ends unmarked (a half mark would refuse that very run and send every later command nowhere)
for how in fail truncate; do
  rm -rf "${T}/old" "${T}/new" "${T}"/new.failed-*; office_tree "${T}/old"; : > "${T}/log"
  DGO_HOME_MOVE_TEST_MARK="${how}" DGO_HOME_MOVE_TEST_SLEEP=0 mv_ move --to "${T}/new" && bad "an unmarked move was accepted" || true
  grep -q "^run-in ${T}/old" "${T}/log" && grep -A1 "^run-in ${T}/old" "${T}/log" | grep -q "admitted=1" \
    && [ ! -e "${T}/old/MOVED-TO.txt" ] && ! grep -q '^desktop-shortcut' "${T}/log" \
    && ok "a mark C: will not take (${how}): the office runs from the old folder again, unmarked, no shortcut" \
    || bad "mark (${how}): $(cat "${T}/log") $(tail -3 "${T}/out")"
done
# a moved folder runs no compose at all (scripts/dc reads lib.sh, not bbox's guard)
printf '%s\n%s\n' "${T}/new" 'x' > "${T}/old/MOVED-TO.txt"
( cd "${T}/old" && . scripts/lib.sh && compose_args 2>&1 ) | grep -q "MOVED-TO.txt-this-folder-was-moved.yml" \
  && ok "compose in a moved folder is handed a file that does not exist: it refuses" || bad "compose in a moved folder"
rm -f "${T}/old/MOVED-TO.txt"

# the run in the new folder fails: back where it was, from the old folder; nothing marked; the copy kept for a look
rm -rf "${T}/old" "${T}/new"; office_tree "${T}/old"; : > "${T}/log"
STUB_FAIL_IN="${T}/new" mv_ move --to "${T}/new" && bad "a failed run was accepted" || true
grep -q "^run-in ${T}/old" "${T}/log" && [ ! -f "${T}/old/MOVED-TO.txt" ] && ! grep -q desktop-shortcut "${T}/log" \
  && ok "a run that fails in the new folder: the office runs again from the old one, nothing marked" \
  || bad "failed run: $(cat "${T}/log") $(tail -3 "${T}/out")"

# both runs fail (the new folder's, then the old one's): the old folder's run is tried ONCE — never again by the error
# trap — the copy is set aside, and the branch's own message is the last word
rm -rf "${T}/old" "${T}/new" "${T}"/new.failed-*; office_tree "${T}/old"; : > "${T}/log"
STUB_FAIL_ALL=1 mv_ move --to "${T}/new" && bad "a move whose runs all failed was accepted" || true
[ "$(grep -c "^run-in ${T}/old" "${T}/log")" = 1 ] && ls -d "${T}"/new.failed-* >/dev/null 2>&1 \
  && grep -q "the copy is set aside" "${T}/out" && ! grep -q "was cut" "${T}/out" \
  && ok "both runs fail: the old folder's run once, the copy set aside, no second recovery" \
  || bad "double recovery: $(cat "${T}/log") $(tail -4 "${T}/out")"

# a copy that differs: exactly the containers that ran come back, the partial copy is removed, nothing marked
mkdir -p "${T}/fakebin"
cat > "${T}/fakebin/tar" <<'EOF'
#!/bin/sh
case " $* " in *" -xpf "*) /bin/tar "$@"; rc=$?; rm -f "$(echo "$@" | sed -n 's/.*-C \([^ ]*\).*/\1/p')/data/app/db"; exit $rc ;; esac
exec /bin/tar "$@"
EOF
chmod +x "${T}/fakebin/tar"; rm -rf "${T}/old" "${T}/new"; office_tree "${T}/old"; : > "${T}/log"
( cd "${T}/old" && PATH="${T}/fakebin:${PATH}" bash scripts/home-move.sh move --to "${T}/new" ) > "${T}/out" 2>&1 \
  && bad "a differing copy was accepted" || true
grep -qx "start-these c1 c2" "${T}/log" && [ ! -e "${T}/new" ] && [ ! -f "${T}/old/MOVED-TO.txt" ] \
  && ok "a copy that differs: exactly the containers that ran start again, the partial copy removed" \
  || bad "differing copy: $(cat "${T}/log") $(tail -3 "${T}/out")"
rm -rf "${T}"
[ "${fail}" = 0 ] && echo "test_home_move: PASS" || echo "test_home_move: FAIL"
exit "${fail}"
