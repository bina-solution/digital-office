#!/usr/bin/env bash
# test_comment_files.sh — a comment given as `@<file>` is the file's text, in every form the hook takes.
#
# What is proved here, with the REAL hooks/tasks, where.sh and batch_files.py in a scratch copy of the repo's
# layout (docker is a stand-in that logs what the applier was given), each against the defect it closes
# (issues/tasks-comment-posts-a-positional-at-file-as-its-path.yaml, issues/a-comment-given-as-at-file-is-
# posted-as-the-path-so-a-handoff-never-reaches-its-item.yaml: seven handoff comments went in as paths):
#   1. `comment <REF> @<file>` gives the applier the file's text, never the path;
#   2. `comment <REF> @<missing>` is refused with exit 2 and nothing reaches the applier;
#   3. a comment of several words that starts with `@` («@azaria look») is words, as before;
#   4. `--comment @<file>` is unchanged;
#   5. a `batch @<file>` whose line says `"comment": "@<file>"` gives the applier the file's text;
#   6. a batch line naming a missing file is refused with its line number, and nothing is sent;
#   7. a batch with no `@` comment is sent exactly as written;
#   8. unquoted words that start with `@` («comment DGO-1 @azaria please look») are words, never a file;
#   9. a `--comment @<file>` whose TEXT is one `@word` is sent as that text, not read a second time;
#  10. a kept write replayed from the outbox is never refused for a missing file (it would hold the queue);
#  11. a batch line naming an EMPTY file is refused (tasks.py would drop the comment without a word).
#
#   bash apps/project-pln/test_comment_files.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "${T}"' EXIT
mkdir -p "${T}/scripts" "${T}/apps/project-pln/hooks" "${T}/apps/computers" "${T}/.generated/registry"
for f in hooks/tasks where.sh outbox.py batch_files.py; do
  tr -d '\r' < "${HERE}/${f}" > "${T}/apps/project-pln/${f}"
done
printf 'workspace:\n  slug: bina\n' > "${T}/apps/project-pln/bootstrap.yaml"
: > "${T}/apps/project-pln/tasks.py"          # the applier's body is never reached: dcx is a stand-in
printf 'apps:\n  project-pln: hp-laptop\n' > "${T}/apps/computers/herd.yaml"
LOG="${T}/calls.log"
cat > "${T}/scripts/lib.sh" <<'EOF'
say()  { echo "[bbox] $*"; }
c0=""; c1=""; cr=""; cg=""; cy=""; DN=vps1
npath() { printf '%s' "$1"; }
read_env() { grep -E "^$1=" "${REPO_ROOT}/.env" 2>/dev/null | head -1 | cut -d= -f2-; }
running() { true; }                                    # a local project-pln container
dcx() {                                                # the applier's argv, one per line, after a marker
  case " $* " in *"python3 -c"*) return 0 ;; esac      # where.sh's reachability probe
  case " $* " in *"python3 - "*)
    local seen=0
    for a in "$@"; do
      [ "${seen}" = 1 ] && printf '%s\n' "${a}" >> "${STUB_LOG}"
      [ "${a}" = "-" ] && seen=1
    done ;;
  esac
  return 0
}
EOF
printf '#!/usr/bin/env bash\nexit 0\n' > "${T}/bbox"; chmod +x "${T}/bbox"
FAILS=0
check() {   # check <name> <ok?> [what was seen]
  if [ "$2" = 0 ]; then echo "PASS  $1"; else echo "FAIL  $1"; printf '%s\n' "${3:-}" | sed 's/^/        /'; FAILS=$((FAILS + 1)); fi
}
mkdir -p "${T}/tmp"
hook() { : > "${LOG}"; (cd "${T}" && TMPDIR="${T}/tmp" STUB_LOG="${LOG}" bash "${T}/apps/project-pln/hooks/tasks" "$@" 2>&1); }

printf 'דו"ח מלא: שורה ראשונה\nשורה שנייה עם $HOME ו-`backtick`\n' > "${T}/report.md"

# 1. positional @<file>
out="$(hook comment DGO-1 @report.md)"; rc=$?
[ "${rc}" = 0 ] && grep -qF 'דו"ח מלא: שורה ראשונה' "${LOG}" && grep -qF '$HOME ו-`backtick`' "${LOG}" \
  && ! grep -qF '@report.md' "${LOG}"
check "comment <REF> @<file> sends the file's text" $? "rc=${rc} ${out} | applier got: $(cat "${LOG}")"

# 2. positional @<missing>
out="$(hook comment DGO-1 @nope.md)"; rc=$?
[ "${rc}" = 2 ] && printf '%s' "${out}" | grep -qF 'comment @nope.md: no such file' && [ ! -s "${LOG}" ]
check "comment <REF> @<missing> is refused, nothing sent" $? "rc=${rc} ${out} | applier got: $(cat "${LOG}")"

# 3. words that start with @
out="$(hook comment DGO-1 "@azaria look at this")"; rc=$?
[ "${rc}" = 0 ] && grep -qxF '@azaria look at this' "${LOG}"
check "a comment of words starting with @ is words" $? "rc=${rc} ${out} | applier got: $(cat "${LOG}")"

# 4. --comment @<file> unchanged
out="$(hook comment DGO-1 --comment @report.md)"; rc=$?
[ "${rc}" = 0 ] && grep -qF 'דו"ח מלא: שורה ראשונה' "${LOG}" && ! grep -qF '@report.md' "${LOG}"
check "--comment @<file> sends the file's text" $? "rc=${rc} ${out} | applier got: $(cat "${LOG}")"

# 5. batch line with "comment": "@<file>"
printf '%s\n' '{"verb":"comment","ref":"DGO-1","comment":"@report.md"}' '{"verb":"start","ref":"DGO-2"}' > "${T}/a.jsonl"
out="$(hook batch @a.jsonl)"; rc=$?
[ "${rc}" = 0 ] && grep -qF 'דו\"ח מלא: שורה ראשונה' "${LOG}" && ! grep -qF '@report.md' "${LOG}" \
  && grep -qF '{"verb":"start","ref":"DGO-2"}' "${LOG}" && [ -z "$(ls -A "${T}/tmp")" ]
check "batch: a line's @<file> comment is the file's text, and the copy is removed" $? \
  "rc=${rc} ${out} | applier got: $(cat "${LOG}")"

# 6. batch line naming a missing file
printf '%s\n' '{"verb":"start","ref":"DGO-2"}' '{"verb":"comment","ref":"DGO-1","comment":"@gone.md"}' > "${T}/b.jsonl"
out="$(hook batch @b.jsonl)"; rc=$?
[ "${rc}" = 2 ] && printf '%s' "${out}" | grep -qF 'line 2: comment @gone.md: no such file' && [ ! -s "${LOG}" ]
check "batch: a missing comment file is refused by line, nothing sent" $? "rc=${rc} ${out} | applier got: $(cat "${LOG}")"

# 7. batch with no @ comment: sent as written
printf '%s\n' '{"verb":"comment","ref":"DGO-1","comment":"plain words"}' > "${T}/c.jsonl"
out="$(hook batch @c.jsonl)"; rc=$?
[ "${rc}" = 0 ] && [ "$(cat "${LOG}")" = "batch
$(cat "${T}/c.jsonl")" ]
check "batch without @ comments is sent exactly as written" $? "rc=${rc} ${out} | applier got: $(cat "${LOG}")"

# 8. unquoted words starting with @
out="$(hook comment DGO-1 @azaria please look)"; rc=$?
[ "${rc}" = 0 ] && grep -qxF '@azaria' "${LOG}" && grep -qxF 'look' "${LOG}"
check "unquoted words starting with @ are words" $? "rc=${rc} ${out} | applier got: $(cat "${LOG}")"

# 9. --comment @<file> whose text is one @word
printf '@azaria' > "${T}/mention.md"
out="$(hook comment DGO-1 --comment @mention.md)"; rc=$?
[ "${rc}" = 0 ] && grep -qxF '@azaria' "${LOG}"
check "--comment @<file> holding «@word» is that text" $? "rc=${rc} ${out} | applier got: $(cat "${LOG}")"

# 10. a replay is never refused
out="$(PLN_OUTBOX_REPLAY=1 hook comment DGO-1 @gone.md)"; rc=$?
! printf '%s' "${out}" | grep -qF 'no such file'
check "a replayed write is not refused for a missing file" $? "rc=${rc} ${out}"

# 11. batch line naming an empty file
: > "${T}/empty.md"
printf '%s\n' '{"verb":"comment","ref":"DGO-1","comment":"@empty.md"}' > "${T}/d.jsonl"
out="$(hook batch @d.jsonl)"; rc=$?
[ "${rc}" = 2 ] && printf '%s' "${out}" | grep -qF 'line 1: comment @empty.md: the file is empty' && [ ! -s "${LOG}" ]
check "batch: an empty comment file is refused" $? "rc=${rc} ${out} | applier got: $(cat "${LOG}")"

echo; [ "${FAILS}" = 0 ] && echo "ALL PASS" || { echo "${FAILS} FAILED"; exit 1; }
