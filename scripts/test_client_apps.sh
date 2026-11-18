#!/usr/bin/env bash
# test_client_apps.sh — scripts/client-apps.sh on a throwaway checkout and a local «private» repository (DGO-1819).
# Run: bash scripts/test_client_apps.sh   (git and tar; no network, nothing outside a temp directory)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
T="$(mktemp -d "${TMPDIR:-/tmp}/client-apps-test.XXXXXX")"
trap 'rm -rf "${T}"' EXIT
FAIL=0
check() { if eval "$1"; then echo "ok   $2"; else echo "FAIL $2"; FAIL=1; fi; }
g() { git -c user.email=t@example.invalid -c user.name=t "$@"; }

# the office's checkout: the public tree with one app of its own, and this script with lib.sh
O="${T}/office"; mkdir -p "${O}/scripts" "${O}/apps/notes"
cp "${HERE}/client-apps.sh" "${HERE}/lib.sh" "${O}/scripts/"
echo '{"id":"notes","layer":3}' > "${O}/apps/notes/app.json"
printf '#!/usr/bin/env bash\necho "bbox $*" >> "%s/ran"\n' "${T}" > "${O}/bbox"; chmod +x "${O}/bbox"
echo ".env" > "${O}/.gitignore"                     # as the office's own: .env is never in the tree
( cd "${O}" && g init -q && g add -A && g commit -qm public )
# the client's private repository: two apps of its own, and one that would shadow the public tree's
P="${T}/private"; mkdir -p "${P}/apps/books/static" "${P}/apps/ledger" "${P}/apps/notes" "${P}/apps/Bad_Id"
echo '{"id":"books","layer":3}' > "${P}/apps/books/app.json"; echo "<p>books</p>" > "${P}/apps/books/static/index.html"
echo '{"id":"ledger","layer":3}' > "${P}/apps/ledger/app.json"
echo '{"id":"notes","layer":3}' > "${P}/apps/notes/app.json"; echo "not ours" > "${P}/apps/notes/x"
echo '{"id":"Bad_Id","layer":3}' > "${P}/apps/Bad_Id/app.json"
( cd "${P}" && g init -q -b main && g add -A && g commit -qm apps )
run() { ( cd "${O}" && REPO_ROOT="${O}" DGO_CLIENT_APPS_DIR="${T}/side" bash scripts/client-apps.sh "$@" ); }

echo "DGO_CLIENT_APPS_REPO=" > "${O}/.env"
check '[ "$(run status)" = "client-apps: none declared (DGO_CLIENT_APPS_REPO is empty) — this office has no apps of its own" ]' \
  "nothing declared: said, nothing done"
printf 'DGO_CLIENT_APPS_REPO=%s\nDGO_CLIENT_APPS_REF=main\n' "${P}" > "${O}/.env"
run pull --dry-run > "${T}/dry" 2>&1
check '[ ! -d "${O}/apps/books" ] && grep -q "would clone" "${T}/dry"' "a dry run places nothing"
run pull > "${T}/out" 2>&1
check '[ -f "${O}/apps/books/static/index.html" ] && [ -f "${O}/apps/ledger/app.json" ]' "the client's apps are placed at apps/<id>/"
check '[ ! -f "${O}/apps/notes/x" ] && grep -q "public tree" "${T}/out"' "an app the public tree tracks is never replaced (said)"
check '[ ! -d "${O}/apps/Bad_Id" ] && grep -q "not an app id" "${T}/out"' "a directory that is not an app id is skipped (said)"
check '[ -z "$(git -C "${O}" status --porcelain)" ]' "the checkout stays clean: its own .git/info/exclude names them"
check 'grep -q "^bbox run" "${T}/ran"' "the apps changed: bbox run"
: > "${T}/ran"; run pull > "${T}/out2" 2>&1
check '[ ! -s "${T}/ran" ] && grep -q "nothing changed" "${T}/out2"' "a second pull with nothing new runs nothing"
echo "hand edit" > "${O}/apps/books/static/index.html"
run status > "${T}/st1" 2>&1
check 'grep -q "books: placed, DIFFERS" "${T}/st1"' "status says when a placed app was edited by hand"
( cd "${P}" && g rm -rq apps/ledger && g commit -qm "ledger retired" )
run pull > "${T}/out3" 2>&1
check '[ ! -d "${O}/apps/ledger" ] && grep -q "removed apps/ledger" "${T}/out3" && ! grep -q "/apps/ledger/" "${O}/.git/info/exclude"' \
  "an app the repository dropped is removed from apps/ and from the exclude"
check '[ "$(cat "${O}/apps/books/static/index.html")" = "<p>books</p>" ]' "the hand edit is replaced by the repository's"
check '[ -d "${O}/apps/notes" ] && [ -z "$(git -C "${O}" status --porcelain)" ]' "the public tree's app untouched, checkout clean"

# the second reader's blockers: an app's own data is never touched; a git error stops everything; the office's own
# exclude lines stay; a linked app is skipped; one pull at a time; a changed repository is followed
mkdir -p "${O}/apps/books/data"; echo "the client's rows" > "${O}/apps/books/data/db"
echo "/apps/mylocal/" >> "${O}/.git/info/exclude"
( cd "${P}" && echo "<p>books v2</p>" > apps/books/static/index.html && ln -s books apps/alias && g add -A && g commit -qm v2 )
run pull > "${T}/out4" 2>&1
check '[ "$(cat "${O}/apps/books/data/db")" = "the client'"'"'s rows" ] && [ "$(cat "${O}/apps/books/static/index.html")" = "<p>books v2</p>" ]' \
  "a pull replaces the repository's files and never touches the app's own data (apps/books/data)"
check 'grep -q "^/apps/mylocal/$" "${O}/.git/info/exclude" && [ ! -e "${O}/apps/alias" ] && grep -q "is a link" "${T}/out4"' \
  "the office's own exclude line stays; an app that is a link in the repository is skipped (said)"
( cd "${P}" && g rm -rq apps/books && g commit -qm "books retired" )
run pull > "${T}/out5" 2>&1
check '[ "$(cat "${O}/apps/books/data/db")" = "the client'"'"'s rows" ] && [ ! -e "${O}/apps/books/app.json" ] && grep -q "KEPT" "${T}/out5"' \
  "an app the repository dropped loses its files, never its data: the folder is KEPT and said"
check '[ -z "$(git -C "${O}" status --porcelain)" ]' "…and the kept folder stays named in the exclude: the checkout is clean"
mkdir -p "${T}/fakebin"; REALGIT="$(command -v git)"
printf '#!/usr/bin/env bash\ncase "$*" in *ls-files*apps/*) exit 128 ;; esac\nexec "%s" "$@"\n' "${REALGIT}" > "${T}/fakebin/git"
chmod +x "${T}/fakebin/git"
( cd "${P}" && mkdir -p apps/notes2 && echo '{"id":"notes2","layer":3}' > apps/notes2/app.json && g add -A && g commit -qm n2 )
( cd "${O}" && PATH="${T}/fakebin:${PATH}" REPO_ROOT="${O}" DGO_CLIENT_APPS_DIR="${T}/side" bash scripts/client-apps.sh pull ) > "${T}/out6" 2>&1
rc6=$?
check '[ "${rc6}" != 0 ] && [ ! -e "${O}/apps/notes2" ] && [ -f "${O}/apps/notes/app.json" ] && grep -q "could not list" "${T}/out6"' \
  "git failing to list the checkout STOPS the pull: nothing placed, the public app untouched (never read as «not tracked»)"
mkdir "${O}/.git/info/client-apps.lock"
run pull > "${T}/out7" 2>&1; rc7=$?
check '[ "${rc7}" != 0 ] && grep -q "another pull is running" "${T}/out7"' "one pull at a time"
rmdir "${O}/.git/info/client-apps.lock"
P2="${T}/private2"; git clone -q "${P}" "${P2}"
printf 'DGO_CLIENT_APPS_REPO=%s\n' "${P2}" > "${O}/.env"; run pull >/dev/null 2>&1
check '[ "$(git -C "${T}/side" remote get-url origin)" = "${P2}" ]' "a changed DGO_CLIENT_APPS_REPO is followed, not ignored"
printf 'DGO_CLIENT_APPS_REPO=https://someone:CHANGE_ME@git.example.invalid/acme/apps.git\n' > "${O}/.env"
run status > "${T}/st2" 2>&1                         # read whole: grep -q in a pipe would SIGPIPE it (pipefail)
check '! grep -q "s3cr3t" "${T}/st2" && grep -q "https://git.example.invalid/acme/apps.git" "${T}/st2"' \
  "a credential in the URL is never said"
printf 'DGO_CLIENT_APPS_REPO=%s\nDGO_CLIENT_APPS_REF=--upload-pack=x\n' "${P}" > "${O}/.env"
check '! run pull >/dev/null 2>&1' "a ref that is an option is refused"
# a client's server with no rsync (Exampleu's, 2026-11-11): the pull places and compares all the same
mkdir -p "${T}/norsync"; printf '#!/bin/sh\necho "rsync: command not found" >&2; exit 127\n' > "${T}/norsync/rsync"
chmod +x "${T}/norsync/rsync"
( cd "${P}" && mkdir -p apps/shelf/static && echo '{"id":"shelf","layer":3}' > apps/shelf/app.json \
  && echo "<p>shelf</p>" > apps/shelf/static/index.html && printf '#!/bin/sh\n' > apps/shelf/run.sh \
  && chmod +x apps/shelf/run.sh && ln -s static/index.html apps/shelf/home.html && g add -A && g commit -qm shelf )
printf 'DGO_CLIENT_APPS_REPO=%s\n' "${P}" > "${O}/.env"
( cd "${O}" && PATH="${T}/norsync:${PATH}" REPO_ROOT="${O}" DGO_CLIENT_APPS_DIR="${T}/side" bash scripts/client-apps.sh pull ) > "${T}/out8" 2>&1
rc8=$?
( cd "${O}" && PATH="${T}/norsync:${PATH}" REPO_ROOT="${O}" DGO_CLIENT_APPS_DIR="${T}/side" bash scripts/client-apps.sh status ) > "${T}/st8" 2>&1
check '[ "${rc8}" = 0 ] && [ "$(cat "${O}/apps/shelf/static/index.html")" = "<p>shelf</p>" ] && [ -x "${O}/apps/shelf/run.sh" ] && [ "$(readlink "${O}/apps/shelf/home.html")" = static/index.html ]' \
  "no rsync on the server: the pull places the files, the exec bit and a link as a link"
check 'grep -q "shelf: placed, as the clone has it" "${T}/st8"' "no rsync on the server: status compares by content"
chmod -x "${O}/apps/shelf/run.sh"
( cd "${O}" && PATH="${T}/norsync:${PATH}" REPO_ROOT="${O}" DGO_CLIENT_APPS_DIR="${T}/side" bash scripts/client-apps.sh status ) > "${T}/st9" 2>&1
check 'grep -q "shelf: placed, DIFFERS" "${T}/st9"' "a lost exec bit is a difference"

# the client's own documents (DGO-1873): context/<path> is placed at <path>, under ai/context/ and research_notes/ only
rm -rf "${O}/apps/books"; run pull >/dev/null 2>&1    # settle: the KEPT folder above counts as a change on every pull
mkdir -p "${O}/ai/context" && echo "the public index" > "${O}/ai/context/README.md"
( cd "${O}" && g add ai/context/README.md && g commit -qm "public index" )
mkdir -p "${O}/ai/context/acme" && echo "the office's own" > "${O}/ai/context/acme/own.md"
echo "/ai/context/acme/own.md" >> "${O}/.git/info/exclude"
( cd "${P}" && mkdir -p "context/ai/context/acme/research" "context/research_notes/Acme study 2026" context/scripts \
  && echo "model v1" > context/ai/context/acme/model.md && echo "src" > context/ai/context/acme/research/src.md \
  && echo "a study" > "context/research_notes/Acme study 2026/notes [v1].md" && echo "rm -rf /" > context/scripts/evil.sh \
  && echo "theirs" > context/ai/context/README.md && echo "theirs" > context/ai/context/acme/own.md \
  && echo "x" > context/.env.md && ln -s ../../../../.env context/ai/context/acme/env-link \
  && echo "*.md -diff" > "context/research_notes/Acme study 2026/.gitattributes" \
  && echo "*.tmp" > context/ai/context/acme/.gitignore && g add -A && g commit -qm context )
: > "${T}/ran"; run pull > "${T}/c1" 2>&1; rc=$?
check '[ "${rc}" = 0 ] && [ "$(cat "${O}/ai/context/acme/model.md")" = "model v1" ] && [ -f "${O}/ai/context/acme/research/src.md" ] && [ "$(cat "${O}/research_notes/Acme study 2026/notes [v1].md")" = "a study" ]' \
  "the client's documents are placed at the paths they mirror (a space and a [ in a name included)"
check '[ ! -e "${O}/scripts/evil.sh" ] && [ ! -e "${O}/.env.md" ] && grep -q "context/scripts/evil.sh is not under" "${T}/c1"' \
  "a document outside ai/context/ and research_notes/ is never placed (said)"
check '[ ! -e "${O}/ai/context/acme/env-link" ] && grep -q "env-link is not a plain file" "${T}/c1"' "a link in context/ is skipped (said)"
check '[ ! -e "${O}/research_notes/Acme study 2026/.gitattributes" ] && [ ! -e "${O}/ai/context/acme/.gitignore" ] && grep -q "acme/.gitignore is not under" "${T}/c1"' \
  "a part that starts with «.» (.gitignore, .gitattributes) is never placed (said)"
check '[ "$(cat "${O}/ai/context/README.md")" = "the public index" ] && grep -q "public tree.s own file" "${T}/c1"' \
  "a document the public tree tracks is never replaced (said)"
check '[ "$(cat "${O}/ai/context/acme/own.md")" = "the office'"'"'s own" ] && grep -q "office.s own file" "${T}/c1"' \
  "a file of the office's own that this did not place is left as it is (said)"
check '[ -z "$(git -C "${O}" status --porcelain)" ]' "the checkout stays clean: each placed document is in the exclude block"
check '[ ! -s "${T}/ran" ] && grep -q "documents: 3 changed" "${T}/c1"' "documents change no service: no bbox run"
run status > "${T}/c2" 2>&1
check 'grep -q "documents: 3 placed, as the clone has them" "${T}/c2"' "status compares the documents with the clone"
( cd "${P}" && g rm -rq context/ai/context/acme/research && echo "model v2" > context/ai/context/acme/model.md && g add -A && g commit -qm v2 )
run pull > "${T}/c3" 2>&1
check '[ "$(cat "${O}/ai/context/acme/model.md")" = "model v2" ] && [ ! -e "${O}/ai/context/acme/research" ] && [ -d "${O}/ai/context/acme" ]' \
  "a document the repository drops is removed, its empty folder with it; a changed one is replaced"
check '[ -z "$(git -C "${O}" status --porcelain)" ] && ! grep -q "research/src.md" "${O}/.git/info/exclude"' \
  "…and it leaves the exclude block; the checkout is clean"
# the second reader's findings: a placed document the public tree tracks later is the public tree's — never removed
( cd "${O}" && g add -f ai/context/acme/model.md && g commit -qm "the public tree takes model.md" )
( cd "${P}" && g rm -q context/ai/context/acme/model.md && g commit -qm "model dropped" )
run pull > "${T}/c5" 2>&1
check '[ "$(cat "${O}/ai/context/acme/model.md")" = "model v2" ] && grep -q "public tree.s now" "${T}/c5" && [ -z "$(git -C "${O}" status --porcelain)" ]' \
  "a placed document the public tree now tracks is left to it when the repository drops it (said), checkout clean"
# …and a documents failure leaves the apps of the same pull named in the exclude and the record
N="research_notes/Acme study 2026/notes [v1].md"
rm -f "${O}/${N}" && mkdir -p "${O}/${N}" && echo "the office's" > "${O}/${N}/inside"
( cd "${P}" && echo "a study v2" > "context/${N}" && mkdir -p apps/shelf2 && echo '{"id":"shelf2","layer":3}' > apps/shelf2/app.json \
  && g add -A && g commit -qm "shelf2 + study v2" )
run pull > "${T}/c6" 2>&1; rc6b=$?
check '[ "${rc6b}" != 0 ] && [ -f "${O}/apps/shelf2/app.json" ] && grep -q "^/apps/shelf2/$" "${O}/.git/info/exclude" && grep -qx shelf2 "${O}/.git/info/client-apps" && grep -q "documents were NOT placed" "${T}/c6"' \
  "a documents failure is said and fails the pull, but the apps of the same pull are placed, excluded and recorded"
rm -rf "${O:?}/${N}"
( cd "${P}" && g rm -rq context && g commit -qm "no documents" )
run pull > "${T}/c4" 2>&1
check '[ ! -e "${O}/ai/context/acme/research" ] && [ ! -e "${O}/research_notes/Acme study 2026" ] && [ -f "${O}/ai/context/README.md" ] && [ -f "${O}/ai/context/acme/own.md" ]' \
  "no context/ left: every placed document removed, the public file and the office's own kept"
check '[ ! -e "${O}/.git/info/client-apps.d/_context.files" ] && [ -z "$(git -C "${O}" status --porcelain)" ]' \
  "…the record is gone and the checkout is clean"
[ "${FAIL}" = 0 ] && echo "test_client_apps: OK" || { echo "test_client_apps: FAILED"; exit 1; }
