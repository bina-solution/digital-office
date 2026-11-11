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
    if [ $# -gt 0 ]; then echo "${BEGIN}"; for i in "$@"; do echo "/apps/${i}/"; done; echo "${END}"; fi; } \
    | atomic_write "${EXCLUDE}"
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
}

differs() {   # do the repository's files of app $1 differ from what is placed? (links compared as links, never followed)
  local m; m="$(mktemp)"
  manifest_of_side "$1" > "${m}"
  local out; out="$(rsync -a --dry-run --itemize-changes --files-from="${m}" "${SIDE}/apps/$1/" "${REPO_ROOT}/apps/$1/" 2>&1)"
  rm -f "${m}"
  [ -n "${out}" ]
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
    echo "would check out $(git -C "${SIDE}" rev-parse --short FETCH_HEAD) (the clone is at $(git -C "${SIDE}" rev-parse --short HEAD 2>/dev/null || echo none)) and place: $(git -C "${SIDE}" ls-tree --name-only FETCH_HEAD apps/ 2>/dev/null | sed 's#^apps/##' | tr '\n' ' ')"
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
    rsync -a --files-from="${new}" "${SIDE}/apps/${i}/" "${REPO_ROOT}/apps/${i}/" \
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
  write_exclude "${keep[@]+"${keep[@]}"}" || { echo "client-apps: could not write ${EXCLUDE}" >&2; return 1; }
  printf '%s\n' "${keep[@]+"${keep[@]}"}" | atomic_write "${PLACED}" \
    || { echo "client-apps: could not write ${PLACED}" >&2; return 1; }
  if [ "${changed}" = 1 ] && [ "${run}" = 1 ]; then
    echo "client-apps: the apps changed — bbox run"
    "${REPO_ROOT}/bbox" run
  else
    echo "client-apps: $([ "${changed}" = 1 ] && echo "placed (--no-run: bbox run when ready)" || echo "nothing changed")"
  fi
}

case "${1:-status}" in
  pull) shift; pull "$@" ;;
  status) status ;;
  -h|--help|help) sed -n '2,6p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
  *) echo "client-apps: pull [--dry-run] [--no-run] | status" >&2; exit 2 ;;
esac
