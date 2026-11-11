# _office_branch.sh — sourced by the pre-push and reference-transaction hooks: the office's branch rule, held by git
# itself (DGO-1764, after DGO-1461). Not a hook: git runs only files named after a hook.
#
# WHY IN GIT. The Bash hook (.claude/hooks/office-branch.py) reads a command's TEXT and guesses what git will do; four
# readers in a row found shell shapes it could not read (DGO-1461). Here git hands over what it is about to do — the
# refs a transaction moves, the refs a push sends — whatever the shell syntax, alias, script or tool that asked.
#
# THE RULE (AGENTS.md rule 6): an office works on ONE branch (DGO_BRANCH). It never creates, moves or deletes another
# local branch, never points HEAD at one, never rewrites history it has pushed, and pushes only its own branch, as a
# fast-forward. `DGO_GIT_OVERRIDE=1` on the command is the owner's explicit ask: it passes, and is said. An office
# that declares no branch is not held, and one that declares it but not DGO_BRANCH_ENFORCE=1 is warned, not refused —
# but a Claude session is refused at once (rule 8's stages; ob_enforced).
#
# WHERE IT IS WIRED. `scripts/checkout-owner.sh setup` sets core.hooksPath to the MAIN checkout's scripts/git-hooks, an
# absolute path: a relative one is read from each worktree's own top, so a probe worktree of an older commit would run
# no hook, or its own edited copy.
#
# WHAT IT CANNOT HOLD (measured on git 2.50; the readers):
#   - THE FILES. Git writes the working tree and the index BEFORE the refs, so a refused checkout, switch or reset has
#     already changed the files when the hook says no; a commit after it would carry that change on the office's
#     branch, and its push is a fast-forward. The refusal says so (`git status`), and the Bash hook
#     (.claude/hooks/office-branch.py), which reads the command BEFORE it runs, stays as the first layer.
#   - `branch -c/-C/-m/-M` under the files backend copy or rename without the hook seeing the new name — and
#     `branch -C <other> <office>` from a detached HEAD lands another branch's tip ON the office's branch unseen
#     (pre-push still refuses pushing what is not a fast-forward of it).
#   - `git -c core.hooksPath=…`, a config edit, or a fresh clone runs no hook at all; `push --no-verify` skips pre-push
#     (reference-transaction cannot be skipped so); `git send-pack` runs no pre-push; a git older than 2.46 does not
#     report HEAD's switches; `push.followTags` makes every push carry tags, which pre-push refuses.
#   - A later empty `DGO_BRANCH=` line in the main .env declares no branch, as .env reads (last line wins).
#   - The rewrite check reads what remotes hold from refs/remotes/*/<office>, which this hook does not judge: moving
#     that tracking ref back first lets a reset of pushed commits through here (its push is still refused), and a
#     push to a URL leaves no tracking ref to read.
#   - The office's own agents and the follow image run Debian 12's git 2.39, which reports no HEAD switch; a commit on
#     another branch is refused all the same.
#   - On the HP, setup runs in WSL and writes a /mnt/c/… hooksPath, which Git for Windows cannot resolve, so its git
#     may run no hook at all — unmeasured; `git rev-parse --git-path hooks` from Git Bash there says (DGO-1764).
#   - The rule is read live from the main checkout's working tree: an uncommitted edit of these files, or a rollback
#     to a commit before them, changes it for every worktree at once.
#   - Cost: git runs this hook for every transaction, and a plain fetch makes one per ref it changes (500 new tags:
#     ~30 s on the Mac, all process start-up); an ordinary fetch changes a handful.
# Each of the server-side shapes needs the server's own rule — a GitHub ruleset on the office branches and dgo-stable,
# an owner's setting (item DGO-1764). This holds an office's own agents to the rule; an agent set on breaking it is
# held by the server.

ob_zero() {                       # an all-zero object id: a ref created or deleted
  case "$1" in *[!0]*) return 1 ;; "") return 1 ;; *) return 0 ;; esac
}

ob_env_value() {                  # <top> <KEY>: the last KEY= line of <top>/.env, unquoted, its comment dropped
  [ -n "$1" ] && [ -f "$1/.env" ] || return 0
  sed -n -E "s/^[[:space:]]*(export[[:space:]]+)?$2[[:space:]]*=[[:space:]]*//p" "$1/.env" | tail -1 \
    | sed -E 's/[[:space:]]+#.*$//; s/[[:space:]]+$//; s/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/'
}

ob_env_branch() { ob_env_value "$1" DGO_BRANCH; }

ob_main_top() {                   # the MAIN checkout's top (where the office's .env is), or nothing
  local common
  # CDPATH cleared: an exported one aimed `cd` at another folder, so the main .env was never read (the reader)
  common="$(CDPATH='' cd -P -- "$(git rev-parse --git-common-dir 2>/dev/null)" 2>/dev/null && pwd -P)"
  [ -n "${common}" ] && dirname "${common}"
  return 0
}

# Rule 8, staged: a refusal is a warning until the office says DGO_BRANCH_ENFORCE=1 (its main .env, or the command's
# environment) — the same switch scripts/lib.sh reads for the writers no Bash hook holds (the office's own agents,
# follow, a person at a terminal). A Claude session (CLAUDECODE=1) is held at once: it is held by the Bash hook too.
ob_enforced() {
  [ "${DGO_BRANCH_ENFORCE:-}" = 1 ] || [ "${CLAUDECODE:-}" = 1 ] \
    || [ "$(ob_env_value "$(ob_main_top)" DGO_BRANCH_ENFORCE)" = 1 ]
}

# The hooks' one way out of a refusal: the owner's ask passes and is said; an office not yet enforcing is warned.
ob_refuse() {                     # <why> <the rest of the refusal's sentence>
  if [ "${DGO_GIT_OVERRIDE:-}" = 1 ]; then
    ob_say "DGO_GIT_OVERRIDE=1: $1 — passed on the owner's explicit ask; say so in the report"
    return 0
  fi
  if ! ob_enforced; then
    ob_say "WOULD refuse — $1. Warned only: this office does not enforce yet (DGO_BRANCH_ENFORCE=1 makes it a refusal)"
    return 0
  fi
  ob_say "refused — $1. $2"
  return 1
}

ob_branch() {                     # the office's branch, as the office declares it
  # the MAIN checkout's .env first: it is the office's declaration, and neither a variable on one command
  # (`DGO_BRANCH=x git …`) nor a worktree's own .env may name another branch over it (the reader). Only an office
  # whose main .env declares nothing is read from the environment, then from the worktree's .env.
  local top value
  top="$(ob_main_top)"
  if [ -n "${top}" ]; then
    value="$(ob_env_branch "${top}")"
    if [ -n "${value}" ]; then printf '%s' "${value}"; return 0; fi
  fi
  if [ -n "${DGO_BRANCH:-}" ]; then printf '%s' "${DGO_BRANCH}"; return 0; fi
  ob_env_branch "$(git rev-parse --show-toplevel 2>/dev/null)"
  return 0
}

ob_say() {                        # one line on stderr, which git shows to whoever ran the command
  printf 'office-branch (git): %s\n' "$*" >&2
}
