#!/usr/bin/env bash
# client-apps.sh — a client's OWN apps onto its office, from the client's private repository (DGO-1819).
#
#     ./bbox client-apps pull [--dry-run] [--no-run]   fetch it, place each app under apps/, then `bbox run`
#     ./bbox client-apps status                         what is declared, what is placed, what differs
#
# WHY. A client's office takes code only from the public release, and the public release holds the apps built for a
# client back (scripts/release/public/exclude.txt) — so they had no way onto the office they were built for (issues/
# a-clients-own-apps-have-no-way-onto-that-clients-office-the-public-export-holds-them-back.yaml). A third catalog
# root would have to be taught to the compiler, its Go twin and every gate that lists `apps` and `platform-base`;
# this needs none of it: the apps keep their place, apps/<id>/, as in the company tree.
#
# THE DECLARATION is .env: DGO_CLIENT_APPS_REPO — the client's private repository (git URL; ssh with a read-only
# deploy key), whose apps/<id>/ trees are the apps; DGO_CLIENT_APPS_REF (default main); DGO_CLIENT_APPS_KEYFILE — the
# deploy key's PATH on the host, when the URL is ssh. Empty REPO: this office has no apps of its own.
#
# ONE PULL: the repository is cloned (or fetched) BESIDE the checkout — ${REPO_ROOT}/../dgo-client-apps, never
# inside it — and each of its apps/<id>/ that has an app.json is placed at apps/<id>/ (a copy; the clone stays the
# source). Each placed app is named in the checkout's OWN .git/info/exclude (local to this office, never in any
# repository), so `git status` stays clean, follow.sh's take has nothing to trip on, and no client name reaches the
# public export. An app that would shadow one the public tree tracks is refused — the client's apps add, never
# replace. An app the repository no longer has is removed from apps/ (only one this script placed: the record is
# .git/info/client-apps). Enabling an app stays the office's decision (the apps screen, platform.state.yaml).
#
# THE CLIENT'S OWN DOCUMENTS (DGO-1873). The repository's context/ tree holds the client's model maps, requirements
# and research at the paths they have in the company tree — context/ai/context/exampleu/… is placed at
# ai/context/exampleu/… — so an app's AGENT.md that names them finds them on the client's office too. Only under
# CONTEXT_ROOTS (documents: never code, never .env), only plain files, never over a file the public tree tracks or one
# this script did not place; each placed file is named in the same exclude block, and one the repository drops is
# removed (the record is .git/info/client-apps.d/_context.files). Documents change no service: no `bbox run` for them.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="${REPO_ROOT:-$(cd "${HERE}/.." && pwd -P)}"
export REPO_ROOT
LOG_TAG=client-apps
. "${HERE}/lib.sh"

SIDE="${DGO_CLIENT_APPS_DIR:-${REPO_ROOT}/../dgo-client-apps}"
GITDIR="$(git -C "${REPO_ROOT}" rev-parse --absolute-git-dir 2>/dev/null)" || { echo "client-apps: ${REPO_ROOT} is not a git checkout" >&2; exit 2; }
EXCLUDE="${GITDIR}/info/exclude"
PLACED="${GITDIR}/info/client-apps"                    # the ids this placed, one a line
MANIFESTS="${GITDIR}/info/client-apps.d"                # per id: the repository's files this placed (<id>.files)
BEGIN="# client-apps begin (scripts/client-apps.sh) — local to this office, never committed"
END="# client-apps end"
CONTEXT_ROOTS="ai/context/ research_notes/"            # where a client's documents may be placed — nowhere else
CTX_FILES="${MANIFESTS}/_context.files"                # the context paths this placed, one a line («_» is no app id)

repo="$(read_env_value DGO_CLIENT_APPS_REPO)"
ref="$(read_env_value DGO_CLIENT_APPS_REF)"; ref="${ref:-main}"
key="$(read_env_value DGO_CLIENT_APPS_KEYFILE)"

shown() {   # the repository as it may be said: never a credential in a URL
  printf '%s' "$1" | sed -E 's#(https?://)[^@/]+@#\1#'
}

git_side() {   # git in the side clone, with the deploy key when one is declared — never a prompt, never a hang
  if [ -n "${key}" ]; then
    GIT_SSH_COMMAND="ssh -i '${key//\'/}' -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new" \
      GIT_TERMINAL_PROMPT=0 git -C "${SIDE}" "$@"
  else
    GIT_TERMINAL_PROMPT=0 git -C "${SIDE}" "$@"
  fi
}

ids_in_side() {   # the apps the repository holds: apps/<id>/app.json in a real directory (never a symlink)
  local d
  for d in "${SIDE}"/apps/*/; do
    d="${d%/}"
    [ -L "${d}" ] && { echo "client-apps: apps/${d##*/} is a link in the repository — skipped" >&2; continue; }
    [ -f "${d}/app.json" ] || continue
    d="${d##*/}"
    case "${d}" in *[!a-z0-9-]*|-*|"") echo "client-apps: «${d}» is not an app id (a-z, 0-9, -) — skipped" >&2; continue ;; esac
    printf '%s\n' "${d}"
  done
}

placed_ids() { [ -f "${PLACED}" ] && grep -E '^[a-z0-9][a-z0-9-]*$' "${PLACED}" || true; }

public_tracks() {   # 0: the public tree tracks apps/<id>; 1: it does not; a git error ABORTS (never read as «not»)
  local out
  out="$(git -C "${REPO_ROOT}" ls-files -- "apps/$1")" \
    || { echo "client-apps: git could not list apps/$1 in the checkout — stopping, nothing placed or removed" >&2; exit 1; }
  [ -n "${out}" ]
}

atomic_write() {   # stdin → $1, replaced in one step (a temp file beside it, then mv)
  local tmp; tmp="$(mktemp "$1.XXXXXX")" || return 1
  cat > "${tmp}" && mv -f "${tmp}" "$1" || { rm -f "${tmp}"; return 1; }
}

write_exclude() {   # ONLY this script's block, between its two marker lines, is replaced; every other line stays
  mkdir -p "${GITDIR}/info"
  { [ -f "${EXCLUDE}" ] && awk -v b="${BEGIN}" -v e="${END}" '$0==b{skip=1;next} skip&&$0==e{skip=0;next} !skip{print}' "${EXCLUDE}"
    if [ $# -gt 0 ] || [ -s "${CTX_FILES}" ]; then
      echo "${BEGIN}"; for i in "$@"; do echo "/apps/${i}/"; done
      # a placed document, one exact path a line: a glob character or a trailing space in its name is escaped
      [ -s "${CTX_FILES}" ] && sed -e 's/[][*?\\]/\\&/g' -e 's/ $/\\ /' -e 's#^#/#' "${CTX_FILES}"
      echo "${END}"
    fi; } \
    | atomic_write "${EXCLUDE}"
}

in_context_roots() {   # is $1 (a path relative to the checkout) under one of CONTEXT_ROOTS, with no part that starts with «.»?
  local r
  case "/$1/" in */../*|*/./*|*//*|*/.*) return 1 ;; esac   # .git, .gitignore, .gitattributes: never a document
  for r in ${CONTEXT_ROOTS}; do case "$1" in "${r}"?*) return 0 ;; esac; done
  return 1
}

context_in_side() {   # the repository's context/ files, as their paths in the checkout — plain files under the roots only;
  # a git error returns 1 (never read as «no documents», which would remove every placed one)
  local meta f ls
  ls="$(mktemp)"
  git -C "${SIDE}" -c core.quotePath=false ls-files -s -- context > "${ls}" \
    || { rm -f "${ls}"; echo "client-apps: git could not list the repository's context/ — stopping the documents" >&2; return 1; }
  while IFS=$'\t' read -r meta f; do
    case "${f}" in \"*) echo "client-apps: a context file whose name git must quote is skipped: ${f}" >&2; continue ;; esac
    case "${meta%% *}" in 100644|100755) ;; *) echo "client-apps: ${f} is not a plain file (a link?) — skipped" >&2; continue ;; esac
    f="${f#context/}"
    in_context_roots "${f}" || { echo "client-apps: context/${f} is not under ${CONTEXT_ROOTS% } — skipped" >&2; continue; }
    printf '%s\n' "${f}"
  done < "${ls}"
  rm -f "${ls}"
}

place_context() {   # the repository's documents at their paths; prints how many changed; returns 1 on a failure
  local new tracked kept gone f n=0
  new="$(mktemp)"; tracked="$(mktemp)"; kept="$(mktemp)"; gone="$(mktemp)"
  context_in_side > "${new}.raw" || { rm -f "${new}" "${new}.raw" "${tracked}" "${kept}" "${gone}"; return 1; }
  sort -u "${new}.raw" > "${new}"; rm -f "${new}.raw"
  # never over a file the public tree tracks — asked of git in one call; a git error STOPS (never read as «not»)
  if [ -s "${new}" ]; then
    sed 's#^#:(literal)#' "${new}" | tr '\n' '\0' \
      | xargs -0 git -C "${REPO_ROOT}" -c core.quotePath=false ls-files -- > "${tracked}" \
      || { rm -f "${new}" "${tracked}" "${kept}" "${gone}"; echo "client-apps: git could not list the context paths in the checkout — stopping" >&2; return 1; }
  fi
  while IFS= read -r f; do
    if grep -qxF -- "${f}" "${tracked}"; then
      echo "client-apps: ${f} is the public tree's own file — a client's document never replaces one; skipped" >&2
    elif [ -e "${REPO_ROOT}/${f}" ] && ! { [ -f "${CTX_FILES}" ] && grep -qxF -- "${f}" "${CTX_FILES}"; } \
         && ! cmp -s "${SIDE}/context/${f}" "${REPO_ROOT}/${f}"; then
      echo "client-apps: ${f} is the office's own file, not one this placed — left as it is" >&2
    else
      [ -f "${REPO_ROOT}/${f}" ] && cmp -s "${SIDE}/context/${f}" "${REPO_ROOT}/${f}" || n=$((n + 1))
      printf '%s\n' "${f}" >> "${kept}"
    fi
  done < "${new}"
  if [ -s "${kept}" ]; then
    ( cd "${SIDE}/context" && tar -cf - -T "${kept}" ) | ( cd "${REPO_ROOT}" && tar -xpf - ) \
      || { rm -f "${new}" "${tracked}" "${kept}" "${gone}"; echo "client-apps: could not place the context files" >&2; return 1; }
  fi
  if [ -f "${CTX_FILES}" ]; then                     # what the repository dropped since the last pull, and only that
    comm -23 <(sort -u "${CTX_FILES}") "${kept}" > "${gone}"
    # one the public tree tracks NOW (a take brought it) is the public tree's: left to it, never removed
    : > "${tracked}"
    if [ -s "${gone}" ]; then
      sed 's#^#:(literal)#' "${gone}" | tr '\n' '\0' \
        | xargs -0 git -C "${REPO_ROOT}" -c core.quotePath=false ls-files -- > "${tracked}" \
        || { rm -f "${new}" "${tracked}" "${kept}" "${gone}"; echo "client-apps: git could not list the dropped documents in the checkout — stopping" >&2; return 1; }
    fi
    while IFS= read -r f; do
      in_context_roots "${f}" || continue
      if grep -qxF -- "${f}" "${tracked}"; then echo "client-apps: ${f} is the public tree's now — left to it" >&2; continue; fi
      rm -f -- "${REPO_ROOT}/${f}" && n=$((n + 1))
      f="${f%/*}"                                     # its folders, once empty, up to the root they are under
      while [ "${f}" != "${f%/*}" ] && in_context_roots "${f}" && rmdir "${REPO_ROOT}/${f}" 2>/dev/null; do f="${f%/*}"; done
    done < "${gone}"
  fi
  atomic_write "${CTX_FILES}" < "${kept}" || { rm -f "${new}" "${tracked}" "${kept}" "${gone}"; return 1; }
  [ -s "${CTX_FILES}" ] || rm -f "${CTX_FILES}"
  rm -f "${new}" "${tracked}" "${kept}" "${gone}"
  echo "${n}"
}

manifest_of_side() {   # the repository's own files of an app, relative to apps/<id>/ — what a pull places
  git -C "${SIDE}" ls-files -- "apps/$1" | sed "s#^apps/$1/##"
}

status() {
  if [ -z "${repo}" ]; then echo "client-apps: none declared (DGO_CLIENT_APPS_REPO is empty) — this office has no apps of its own"; return 0; fi
  echo "client-apps: $(shown "${repo}") @ ${ref}$([ -n "${key}" ] && echo ' (deploy key)')"
  if [ -d "${SIDE}/.git" ]; then echo "  the clone: ${SIDE} at $(git -C "${SIDE}" rev-parse --short HEAD 2>/dev/null)"; else echo "  the clone: none yet (pull)"; fi
  local i
  for i in $(placed_ids); do
    if [ ! -d "${REPO_ROOT}/apps/${i}" ]; then
      echo "  ${i}: recorded as placed, MISSING from apps/"
    elif [ -d "${SIDE}/apps/${i}" ] && ! differs "${i}"; then
      echo "  ${i}: placed, as the clone has it"
    else
      echo "  ${i}: placed, DIFFERS from the clone (a hand edit on the office? the next pull replaces those files)"
    fi
  done
  if [ -s "${CTX_FILES}" ]; then
    local f nd=0 nall=0
    while IFS= read -r f; do
      nall=$((nall + 1))
      { [ -f "${REPO_ROOT}/${f}" ] && [ -f "${SIDE}/context/${f}" ] && cmp -s "${SIDE}/context/${f}" "${REPO_ROOT}/${f}"; } || nd=$((nd + 1))
    done < "${CTX_FILES}"
    if [ "${nd}" = 0 ]; then echo "  documents: ${nall} placed, as the clone has them"
    else echo "  documents: ${nall} placed, ${nd} DIFFER from the clone or are missing (the next pull replaces them)"; fi
  fi
}

differs() {   # do the repository's files of app $1 differ from what is placed? (links compared as links, never followed)
  # cmp and readlink, not rsync: a client's server may have no rsync (Exampleu's has none, 2026-11-11) — and a failed
  # read must count as «differs», never as «the same»
  local m f s t d=1; m="$(mktemp)"
  manifest_of_side "$1" > "${m}" || { rm -f "${m}"; return 0; }
  while IFS= read -r f; do
    s="${SIDE}/apps/$1/${f}"; t="${REPO_ROOT}/apps/$1/${f}"
    if [ -L "${s}" ]; then
      { [ -L "${t}" ] && [ "$(readlink "${s}")" = "$(readlink "${t}")" ]; } || { d=0; break; }
    else
      { [ -f "${t}" ] && [ ! -L "${t}" ] && cmp -s "${s}" "${t}"; } || { d=0; break; }
      { [ -x "${s}" ] && [ -x "${t}" ]; } || { [ ! -x "${s}" ] && [ ! -x "${t}" ]; } || { d=0; break; }
    fi
  done < "${m}"
  rm -f "${m}"
  return "${d}"
}

place() {   # copy exactly the files listed in $2 (relative to apps/$1) from the clone into apps/$1 — links as links,
  # modes kept; tar, not rsync (see differs)
  ( cd "${SIDE}/apps/$1" && tar -cf - -T "$2" ) | ( cd "${REPO_ROOT}/apps/$1" && tar -xpf - )
}

remove_listed() {   # remove from apps/$1 exactly the files listed in $2 (relative paths) — nothing else, never outside
  local f
  while IFS= read -r f; do
    case "${f}" in ""|/*|..|../*|*/../*|*/..) continue ;; esac
    rm -f -- "${REPO_ROOT}/apps/$1/${f}"
  done < "$2"
}

pull() {
  local dry=0 run=1 a
  for a in "$@"; do case "${a}" in --dry-run) dry=1 ;; --no-run) run=0 ;; *) echo "client-apps pull [--dry-run] [--no-run]" >&2; return 2 ;; esac; done
  [ -n "${repo}" ] || { echo "client-apps: DGO_CLIENT_APPS_REPO is empty — nothing to pull"; return 0; }
  case "${ref}" in *[!A-Za-z0-9._/-]*|-*) echo "client-apps: DGO_CLIENT_APPS_REF «${ref}» is not a ref" >&2; return 2 ;; esac
  mkdir -p "${GITDIR}/info" "${MANIFESTS}"
  # one pull at a time (a directory lock: portable, atomic); released however this returns
  mkdir "${GITDIR}/info/client-apps.lock" 2>/dev/null \
    || { echo "client-apps: another pull is running (${GITDIR}/info/client-apps.lock) — not now" >&2; return 1; }
  trap 'rmdir "${GITDIR}/info/client-apps.lock" 2>/dev/null' EXIT
  if [ ! -d "${SIDE}/.git" ]; then
    [ "${dry}" = 1 ] && { echo "would clone $(shown "${repo}") into ${SIDE} and place its apps"; return 0; }
    mkdir -p "${SIDE}" && git_side init -q && git_side remote add origin "${repo}" \
      || { echo "client-apps: could not start the clone at ${SIDE}" >&2; return 1; }
  else
    git_side remote set-url origin "${repo}" || return 1   # a changed declaration is followed, not ignored
  fi
  git_side fetch -q --depth 1 origin "${ref}" || { echo "client-apps: could not fetch ${ref} from $(shown "${repo}")" >&2; return 1; }
  if [ "${dry}" = 1 ]; then
    echo "would check out $(git -C "${SIDE}" rev-parse --short FETCH_HEAD) (the clone is at $(git -C "${SIDE}" rev-parse --short HEAD 2>/dev/null || echo none)) and place: $(git -C "${SIDE}" ls-tree --name-only FETCH_HEAD apps/ 2>/dev/null | sed 's#^apps/##' | tr '\n' ' ')· documents: $(git -C "${SIDE}" ls-tree -r --name-only FETCH_HEAD context/ 2>/dev/null | grep -c .)"
    return 0
  fi
  git_side checkout -q --detach FETCH_HEAD || { echo "client-apps: could not check ${ref} out" >&2; return 1; }

  local want=() keep=() i changed=0 new old
  while IFS= read -r i; do want+=("${i}"); done < <(ids_in_side)
  for i in "${want[@]+"${want[@]}"}"; do
    if public_tracks "${i}"; then
      echo "client-apps: apps/${i} is the public tree's own app — a client's app never replaces one; skipped" >&2
      continue
    fi
    keep+=("${i}")
    new="$(mktemp)"; old="${MANIFESTS}/${i}.files"
    manifest_of_side "${i}" | sort > "${new}"
    if [ -d "${REPO_ROOT}/apps/${i}" ] && ! differs "${i}" \
       && { [ ! -f "${old}" ] || [ -z "$(comm -23 <(sort "${old}") "${new}")" ]; }; then
      [ -f "${old}" ] || atomic_write "${old}" < "${new}"
      rm -f "${new}"; continue
    fi
    changed=1
    mkdir -p "${REPO_ROOT}/apps/${i}"
    # exactly the repository's own files (links as links); nothing else in the folder — the app's data — is touched
    place "${i}" "${new}" \
      || { rm -f "${new}"; echo "client-apps: could not place apps/${i}" >&2; return 1; }
    if [ -f "${old}" ]; then                         # what the repository dropped since the last pull, and only that
      comm -23 <(sort "${old}") "${new}" > "${new}.gone"
      remove_listed "${i}" "${new}.gone"; rm -f "${new}.gone"
    fi
    atomic_write "${old}" < "${new}"; rm -f "${new}"
    echo "placed apps/${i}"
  done
  for i in $(placed_ids); do                        # gone from the repository: its files removed — never its data
    case " ${want[*]+"${want[*]}"} " in *" ${i} "*) continue ;; esac
    if public_tracks "${i}"; then echo "client-apps: apps/${i} is the public tree's now — left to it" >&2; continue; fi
    changed=1
    [ -f "${MANIFESTS}/${i}.files" ] && remove_listed "${i}" "${MANIFESTS}/${i}.files"
    rm -f "${MANIFESTS}/${i}.files"
    [ -d "${REPO_ROOT}/apps/${i}" ] && find "${REPO_ROOT}/apps/${i}" -depth -type d -empty -delete 2>/dev/null
    if [ -d "${REPO_ROOT}/apps/${i}" ]; then
      keep+=("${i}")                                  # still named in the exclude: the checkout stays clean
      echo "client-apps: apps/${i} left the repository — its files removed; the folder KEPT: it holds files that did not come from the repository (its data?). Remove it by hand when sure."
    else
      echo "removed apps/${i} (no longer in the repository)"
    fi
  done
  # the documents' failure is theirs: the apps placed above are still named in the exclude and the record
  local nctx ctxfail=0
  nctx="$(place_context)" || { ctxfail=1; nctx=0; }
  [ "${nctx}" = 0 ] || echo "placed the client's documents: ${nctx} changed ($(grep -c . "${CTX_FILES}" 2>/dev/null || echo 0) in all)"
  write_exclude "${keep[@]+"${keep[@]}"}" || { echo "client-apps: could not write ${EXCLUDE}" >&2; return 1; }
  printf '%s\n' "${keep[@]+"${keep[@]}"}" | atomic_write "${PLACED}" \
    || { echo "client-apps: could not write ${PLACED}" >&2; return 1; }
  if [ "${ctxfail}" = 1 ]; then
    [ "${changed}" = 1 ] && [ "${run}" = 1 ] && { echo "client-apps: the apps changed — bbox run"; "${REPO_ROOT}/bbox" run; }
    echo "client-apps: the documents were NOT placed (above) — the apps were" >&2; return 1
  fi
  if [ "${changed}" = 1 ] && [ "${run}" = 1 ]; then
    echo "client-apps: the apps changed — bbox run"
    "${REPO_ROOT}/bbox" run
  else
    echo "client-apps: $([ "${changed}" = 1 ] && echo "placed (--no-run: bbox run when ready)" || { [ "${nctx}" = 0 ] && echo "nothing changed" || echo "the apps did not change"; })"
  fi
}

case "${1:-status}" in
  pull) shift; pull "$@" ;;
  status) status ;;
  -h|--help|help) sed -n '2,6p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
  *) echo "client-apps: pull [--dry-run] [--no-run] | status" >&2; exit 2 ;;
esac
