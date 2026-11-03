#!/usr/bin/env bash
# build-binaries.sh — the release build of the office's three native binaries, the same on a laptop
# and in CI (.github/workflows/release-binaries.yml runs exactly this).
#
# WHAT IT PRODUCES, under dist/ (git-ignored):
#   bin/dgo-install-<os>-<arch>[.exe]    packaging/installer         the tiny signed bootstrapper (core-007)
#   bin/dgo-<os>-<arch>[.exe]            packaging/dgo               DGO core's CLI (core-005, step 1), the
#                                                                    console's files built in (below)
#   bin/forward-auth-<os>-<arch>[.exe]   platform-base/forward-auth  the identity plane (core-006)
#   bin/SHA256SUMS                       one line per file, `sha256sum -c SHA256SUMS` format
#   dl/keys.json                         the signing keys a ROOT vouches for, for this site (made offline
#                                        by the owner, `relsign keys`; this script only checks and publishes it)
#   dl/<os>/<arch>/dgo-core[.exe]        the dgo binary under the NAME the installer downloads
#   dl/<os>/<arch>/manifest.json         site, version, expires, min_bootstrapper, target, payload
#                                        url+sha256+size, signed WHOLE by a key keys.json lists — what the
#                                        installer verifies (packaging/trust). Signed only with
#                                        --sign-key; WITHOUT a key the file is manifest.unsigned.json, the
#                                        bare document, which the installer refuses (fail-closed).
#
# WHY ONE SCRIPT. A release is a fact about bytes, not about a machine: the same command here and on the
# runner, so a checksum CI publishes is one anybody can re-derive from the tag on a laptop.
#
# WHY THESE FLAGS. CGO_ENABLED=0 + -trimpath + -buildvcs=false + one pinned Go toolchain = byte-identical
# builds anywhere (--check-reproducible proves it: build twice, compare). -s -w strips the symbol and
# DWARF tables (about a third of the size) and is part of the recipe, not an option. Stdlib-only modules
# mean no go.sum and nothing fetched: `go build` here never touches the network.
#
# THE STUB'S SIZE IS A GATE: a dgo-install over STUB_MAX_BYTES (4 MiB) fails the build — the plan's
# acceptance (ai/context/dgo-architecture-2026.md §6, step 1), measured in bytes, every target, every run.
#
# THE CONSOLE INSIDE dgo: dgo is built with -tags consoleembed, so `dgo be-child console` serves the
# shell without a checkout. Its one source stays platform-base/console: static/ and modules.yaml exactly
# as committed at HEAD (git archive — never an uncommitted edit, never a file git does not track) are
# copied into snapshot/ of a THROWAWAY COPY of the module, never into the checkout, with HEAD's commit
# time; the copy is vetted and the binary's console proven against its source under the tag
# (internal/console/embedded_test.go) before any target is built from it — skipped with --no-test only.
#
# TRUST (packaging/trust): offline ROOT keys → keys.json (for one site; signing keys, each in
# a window and only for the document types it names) → the manifest (dgo-core-manifest, for the same
# site) → the payload. The roots are PINNED: they are the committed packaging/installer/roots.txt, which
# every stub embeds — no flag, variable or file outside the repository can put other roots in a release.
# A signed release is refused unless roots.txt holds exactly HEAD's bytes, read raw (an edit beside the
# reviewed commit would be embedded as it stands), and HEAD is in a branch of origin (a commit made only
# here was reviewed by nobody). These two stop drift and an unreviewed local commit; they cannot stop a
# hostile build machine, which can forge any local state, a remote-tracking ref included — against that,
# the build is reproducible: anyone can rebuild the tag and compare SHA256SUMS. CI's checkout must fetch
# the branches (fetch-depth: 0) for the second gate to see them. roots.txt names no root until the
# owner's key ceremony (D1), and until then a signed release is refused. The
# ceremony, once, offline, from a directory OUTSIDE the checkout (paths are the caller's; a key is never
# written to, or signed with from, inside the repository):
#   bash <checkout>/packaging/build-binaries.sh --keygen root-a.pem     # and root-b.pem, kept in a safe
#   bash <checkout>/packaging/build-binaries.sh --pubkey root-a.pem     # its line for roots.txt (reviewed, committed)
#   bash <checkout>/packaging/build-binaries.sh --keygen signing.pem    # ONLINE: the DGO_RELEASE_KEY secret
#   bash <checkout>/packaging/build-binaries.sh --relsign keys -signer root-a.pem -site https://digital-office.co.il/dl \
#        -version 1 -key signing.pem -types dgo-core-manifest > keys.json  # 60 days; core manifests only
# A release (--sign-key) then needs that keys.json (--keys FILE, or DGO_KEYS_JSON as its path or its JSON)
# and a release version (dotted numbers: the installer cannot order a pre-release), and refuses without
# them. Each dgo-install gets the download site and the key list's floor (`relsign floor`: its version and
# sha256 — a stub refuses any older list, and any other list under that version, even on a fresh
# computer); every manifest is signed with the online key; and before it says "done" the whole tree is
# checked with the STUB'S OWN rules (TestReleaseTree in packaging/installer): keys.json against the
# committed roots and the floor the stubs carry, every manifest against keys.json, every payload against
# its manifest. Without
# --sign-key the stubs are development builds: they say so on their first screen and install nothing.
# Signing is packaging/relsign (stdlib Go, crypto/ed25519) — nothing but Go is needed; the first version
# signed with openssl and died on Git for Windows' OpenSSL 1.1.1 (no `pkeyutl -rawin`).
#
# USAGE
#   bash packaging/build-binaries.sh [VERSION] [--out DIR] [--targets "os/arch …"] [--only NAME]
#        [--base-url https://digital-office.co.il/dl] [--keys keys.json] [--sign-key KEY.pem]
#        [--expires 90d] [--min-bootstrapper 0.0.0] [--check-reproducible] [--no-test]
#   bash packaging/build-binaries.sh --selftest            throwaway roots → keys.json → signed tree →
#                                                         verified by the stub's rules; forgeries refused
#   bash packaging/build-binaries.sh --keygen KEY.pem      a new key (refuses to overwrite)
#   bash packaging/build-binaries.sh --pubkey KEY.pem      print a key's base64 public half (a roots.txt line)
#   bash packaging/build-binaries.sh --relsign ARGS…       run packaging/relsign (keys, manifest, floor — see its usage)
# VERSION defaults to 0.0.0-dev+<short sha>; a release passes the tag without its leading v (1.4.0).
# --expires is the manifests' life (RFC 3339 or a span: 90d): a stub refuses an expired manifest, so a
# release is re-signed (this script, again) before it runs out. --min-bootstrapper is the oldest stub a
# release accepts; raise it only to retire stubs — a stub that rarely changes keeps its SmartScreen name.
set -euo pipefail

CALLER="$(pwd)" # path arguments mean what they meant where the script was run, not inside the repository
cd "$(dirname "${BASH_SOURCE[0]}")/.."
REPO="$(pwd)"

# Every temporary of a run lives under WORK — the relsign build, the selftest's throwaway keys, the
# reproducibility builds, a key list handed in as JSON — and WORK goes on every way out: success, a
# refusal (die), a failed command under set -e, an interrupt. (Before this, every run that signed or
# self-tested left its relsign build behind in the temp directory.)
WORK="$(mktemp -d)" || { echo "build-binaries: mktemp failed" >&2; exit 1; }
trap 'rm -rf "$WORK"' EXIT
trap 'exit 1' HUP INT TERM

# ── the three modules: name  directory  version-symbol? ───────────────────────────────────────────
MODULES=(
  "dgo-install packaging/installer yes"
  "dgo packaging/dgo yes"
  "forward-auth platform-base/forward-auth no"
)
TARGETS="windows/amd64 windows/arm64 darwin/amd64 darwin/arm64 linux/amd64 linux/arm64"
# Where dgo goes as a command and nothing else: no installer stub (it has no Android path), no
# forward-auth (a server's), no download-tree entry (that tree is what the stub fetches). A phone's own
# office runs in Android's Linux terminal — a Debian VM, linux/arm64 above (DGO-1069). --targets names
# every target of a run, so it builds none of these.
CLI_TARGETS="android/arm64"
OUT="dist"
BASE_URL="https://digital-office.co.il/dl"
STUB_MAX_BYTES=4194304 # 4 MiB — the stub's budget, per target
ROOTS_TXT="packaging/installer/roots.txt" # the release roots, committed; every stub embeds it
SIGN_KEY=""
KEYS_JSON=""
KEYS_FLOOR=""
EXPIRES="90d"
MIN_BOOT="0.0.0"
ONLY=""
CHECK_REPRO=0
RUN_TESTS=1
VERSION=""

die() { echo "build-binaries: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required and not on PATH"; }

# sha256 of one file, hex only — coreutils or macOS.
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

# relsign, built once into WORK the first time it is needed (a second or two), and gone with WORK.
RELSIGN=""
relsign() {
  if [ -z "$RELSIGN" ]; then
    need go
    RELSIGN="$WORK/relsign"; [ "$(go env GOOS)" = windows ] && RELSIGN="$RELSIGN.exe"
    (cd "$REPO/packaging/relsign" && CGO_ENABLED=0 go build -trimpath -o "$RELSIGN" .) || die "could not build packaging/relsign"
  fi
  "$RELSIGN" "$@"
}

# roots_csv TEXT — the roots' base64 public keys, one per line or comma/space-separated, '#' comments
# allowed; printed comma-separated.
roots_csv() { printf '%s\n' "$1" | tr -d '\r' | sed 's/#.*//' | tr ', \t' '\n\n\n' | sed '/^$/d' | paste -sd, - ; }

# from_caller PATH — a path argument as its caller meant it: relative to where the script was run.
from_caller() { case "$1" in /*|[A-Za-z]:[\\/]*) printf '%s' "$1" ;; *) printf '%s/%s' "$CALLER" "$1" ;; esac; }

# outside_repo PATH — a private key never lives in the checkout, where one `git add -A` by any of its
# writers would publish it: not written there, and not signed with from there.
outside_repo() {
  local p="$1" d
  if command -v cygpath >/dev/null 2>&1; then p="$(cygpath -u "$p")"; fi # C:\keys\a.pem as Git Bash sees it
  d="$(cd "$(dirname "$p")" 2>/dev/null && pwd)" || die "$(dirname "$p"): no such directory"
  # -ef compares the directories themselves, not their spelling: case (Windows) and links can't slip by.
  while :; do
    [ "$d" -ef "$REPO" ] && die "$1 is inside the repository — keep release keys outside it (e.g. ~/dgo-keys/)"
    [ "$d" = "$(dirname "$d")" ] && return 0
    d="$(dirname "$d")"
  done
}

# verify_tree DIR SITE STUB FLOOR [ROOTS] — a release tree checked by the stub's OWN rules
# (TestReleaseTree): keys.json against the committed roots (only the selftest passes ROOTS, its
# throwaway ones) and against FLOOR, the key list floor baked into the stubs, each manifest against
# keys.json, each payload against its manifest. One verifier, so a release cannot pass a check the
# installer would fail.
verify_tree() {
  local tree="$1"
  if command -v cygpath >/dev/null 2>&1; then tree="$(cygpath -m "$tree")"; fi # Git Bash: go wants C:/…
  # …and nothing else converted: a root's base64 may begin with '/', which Git Bash would take for a path.
  (cd "$REPO/packaging/installer" && MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' CGO_ENABLED=0 \
     go test -count=1 -run '^TestReleaseTree$' . -args -tree "$tree" -site "$2" -stub "$3" -floor "$4" ${5:+-roots "$5"})
}

# committed FILE — FILE (repository-relative) holds exactly the bytes HEAD records for it, read raw:
# `git cat-file` runs no filter (a clean filter slipped in through GIT_CONFIG_* cannot make an edit look
# committed) and, with --no-replace-objects, no `git replace` stand-in; an index flag or a staged edit
# is not a commit either. Carriage returns are set aside on both sides: a Windows checkout may add
# them, and roots.txt reads them as spaces.
committed() {
  git -C "$REPO" --no-replace-objects cat-file -e "HEAD:$1" 2>/dev/null &&
    cmp -s <(git -C "$REPO" --no-replace-objects cat-file blob "HEAD:$1" | tr -d '\r') <(tr -d '\r' < "$REPO/$1")
}

# on_origin REV — REV is in a branch of origin, as this clone last fetched it: what is signed was pushed
# and reviewed there, not committed only here. (CI's checkout must fetch the branches: fetch-depth: 0.)
on_origin() { [ -n "$(git -C "$REPO" branch -r --list 'origin/*' --contains "$1" 2>/dev/null)" ]; }

selftest() {
  local tmp="$WORK/selftest"; mkdir -p "$tmp"
  local k; for k in root spare signer stranger; do relsign keygen "$tmp/$k.pem"; done
  local roots; roots="$(relsign pubkey "$tmp/root.pem"),$(relsign pubkey "$tmp/spare.pem")"
  [ "$(relsign pubkey "$tmp/root.pem" | base64 -d | wc -c | tr -d ' ')" = "32" ] || die "selftest: a public key is not 32 bytes"
  local site="https://digital-office.co.il/dl" dl="$tmp/dl"
  mkdir -p "$dl/linux/amd64"
  printf 'pretend DGO core' > "$dl/linux/amd64/dgo-core"
  relsign keys -signer "$tmp/root.pem" -site "$site" -version 1 -key "$tmp/signer.pem" -types dgo-core-manifest > "$tmp/keys.good"
  cp "$tmp/keys.good" "$dl/keys.json"
  local floor; floor="$(relsign floor "$tmp/keys.good")"
  relsign manifest -signer "$tmp/signer.pem" -site "$site" -version 1.2.0 -target linux/amd64 -url "$site/linux/amd64/dgo-core" \
    -file "$dl/linux/amd64/dgo-core" -expires 30d > "$dl/linux/amd64/manifest.json"
  verify_tree "$dl" "$site" 1.2.0 "$floor" "$roots" >/dev/null || die "selftest: a tree we just signed does not verify by the stub's rules"
  relsign keys -signer "$tmp/stranger.pem" -site "$site" -version 2 -key "$tmp/signer.pem" -types dgo-core-manifest > "$dl/keys.json"
  if verify_tree "$dl" "$site" 1.2.0 "$floor" "$roots" >/dev/null 2>&1; then die "selftest: a keys.json no root signed still verifies"; fi
  relsign keys -signer "$tmp/root.pem" -site "$site" -version 1 -expires 30d -key "$tmp/signer.pem" -types dgo-core-manifest > "$dl/keys.json"
  if verify_tree "$dl" "$site" 1.2.0 "$floor" "$roots" >/dev/null 2>&1; then die "selftest: a key list other than the one the stubs carry still verifies"; fi
  cp "$tmp/keys.good" "$dl/keys.json"
  printf 'tampered DGO core' > "$dl/linux/amd64/dgo-core"
  if verify_tree "$dl" "$site" 1.2.0 "$floor" "$roots" >/dev/null 2>&1; then die "selftest: a swapped payload still verifies"; fi
  # A run removes its temporaries whichever way it ends: one that builds relsign and succeeds and one that
  # fails (relsign refuses a key list with no -site), each given a TMPDIR of its own, leave it empty.
  local probe="$WORK/probe"; mkdir -p "$probe"
  TMPDIR="$probe" bash "$REPO/packaging/build-binaries.sh" --pubkey "$tmp/root.pem" >/dev/null || die "selftest: --pubkey failed"
  if TMPDIR="$probe" bash "$REPO/packaging/build-binaries.sh" --relsign keys >/dev/null 2>&1; then die "selftest: relsign keys with no -site succeeded"; fi
  [ -z "$(ls -A "$probe")" ] || die "selftest: a run left its temporaries behind: $(ls -A "$probe" | tr '\n' ' ')"
  echo "selftest OK — two roots, keys.json signed by one, a whole-manifest signature by the listed key, the tree verified by the stub's own rules against the floor the stubs carry; a forged keys.json, another list under the stubs' version and a swapped payload refused; a run's temporaries removed whether it succeeds or fails"
}

# guard_relsign ARGS — the private keys a relsign command writes (keygen) or signs with (-signer) stay
# outside the checkout, like --keygen's and --sign-key's.
guard_relsign() {
  [ "${1:-}" != keygen ] || outside_repo "${2:-}"
  local prev="" a
  for a in "$@"; do
    case "$a" in -signer=*|--signer=*) outside_repo "${a#*=}" ;; esac
    case "$prev" in -signer|--signer) outside_repo "$a" ;; esac
    prev="$a"
  done
}

# ── arguments ─────────────────────────────────────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$(from_caller "$2")"; shift 2 ;;
    --targets) TARGETS="$2"; CLI_TARGETS=""; shift 2 ;;
    --only) ONLY="$2"; shift 2 ;;
    --base-url) BASE_URL="${2%/}"; shift 2 ;;
    --roots) die "--roots is gone: a release trusts the committed $ROOTS_TXT and nothing else" ;;
    --keys) KEYS_JSON="$(from_caller "$2")"; shift 2 ;;
    --sign-key) SIGN_KEY="$(from_caller "$2")"; shift 2 ;;
    --expires) EXPIRES="$2"; shift 2 ;;
    --min-bootstrapper) MIN_BOOT="$2"; shift 2 ;;
    --check-reproducible) CHECK_REPRO=1; shift ;;
    --no-test) RUN_TESTS=0; shift ;;
    --selftest) selftest; exit 0 ;;
    --keygen) key="$(from_caller "$2")"; outside_repo "$key"; relsign keygen "$key"
      echo "wrote $key — keep it offline; its public half: $(relsign pubkey "$key")"; exit 0 ;;
    --pubkey) relsign pubkey "$(from_caller "$2")"; exit 0 ;;
    --relsign) shift; cd "$CALLER"; guard_relsign "$@"; relsign "$@"; exit 0 ;;
    -h|--help) sed -n '2,/^[^#]/{/^#/p;}' "$0"; exit 0 ;;
    -*) die "unknown option $1 (see --help)" ;;
    *) VERSION="$1"; shift ;;
  esac
done
# OUT is absolute from here on: --out as the caller meant it, the default `dist` in the checkout. It was
# joined to the checkout below, so an absolute --out became <checkout>//tmp/out (DGO-1038).
case "$OUT" in /*|[A-Za-z]:[\\/]*) ;; *) OUT="$REPO/$OUT" ;; esac
[ -n "$VERSION" ] || VERSION="0.0.0-dev+$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo nogit)"
case "$VERSION" in v*) die "pass the version without its leading v ($VERSION)";; esac
[ -z "${DGO_ROOT_KEYS:-}" ] || die "DGO_ROOT_KEYS is set, but a release trusts the committed $ROOTS_TXT and nothing else — unset it"

need go
# keys.json: --keys FILE, else DGO_KEYS_JSON — a path, or (as a CI variable holds it) the JSON itself.
if [ -z "$KEYS_JSON" ] && [ -n "${DGO_KEYS_JSON:-}" ]; then
  case "$DGO_KEYS_JSON" in
    *'"payloadType"'*) KEYS_JSON="$WORK/keys.json"; printf '%s\n' "$DGO_KEYS_JSON" > "$KEYS_JSON" ;;
    *) KEYS_JSON="$(from_caller "$DGO_KEYS_JSON")" ;;
  esac
fi
# The roots: the committed file and nothing else; each one a base64 32-byte key.
ROOTS="$(roots_csv "$(cat "$REPO/$ROOTS_TXT")")"
for r in ${ROOTS//,/ }; do
  [ "$(printf '%s' "$r" | base64 -d 2>/dev/null | wc -c | tr -d ' ')" = "32" ] || die "$ROOTS_TXT: $r is not the base64 of a 32-byte Ed25519 public key"
done
if [ -n "$SIGN_KEY" ]; then
  [ -f "$SIGN_KEY" ] || die "--sign-key $SIGN_KEY: no such file"
  outside_repo "$SIGN_KEY"
  committed "$ROOTS_TXT" || die "$ROOTS_TXT is not exactly as committed at HEAD (untracked, edited, or no git here) — a release embeds the reviewed, committed roots and nothing else"
  on_origin HEAD || die "HEAD is in no branch of origin — a release is signed from a pushed, reviewed commit, not one made only here (in CI, check out with fetch-depth: 0)"
  [ -n "$ROOTS" ] || die "$ROOTS_TXT names no root yet (the owner's key ceremony, D1: packaging/installer/README.md) — refusing to sign a release no stub could trust"
  [ -n "$KEYS_JSON" ] && [ -f "$KEYS_JSON" ] || die "a release needs the root-signed key list that names --sign-key: --keys keys.json, or DGO_KEYS_JSON as its path or its JSON (made offline: relsign keys)"
  relsign pubkey "$SIGN_KEY" >/dev/null || die "$SIGN_KEY is not an Ed25519 PKCS#8 key"
  case "$VERSION" in ""|*[!0-9.]*|.*|*.|*..*)
    die "a signed release needs a release version — dotted numbers like 1.4.0 — not $VERSION: the installer cannot order a pre-release (build a draft without --sign-key)" ;;
  esac
  KEYS_FLOOR="$(relsign floor "$KEYS_JSON")" || die "$KEYS_JSON is not a key list relsign wrote"
fi

echo "=== build-binaries $VERSION  go: $(go version | cut -d' ' -f3)  targets: $TARGETS$( { [ -z "$ONLY" ] || [ "$ONLY" = dgo ]; } && [ -n "$CLI_TARGETS" ] && echo " (and dgo alone: $CLI_TARGETS)")  stubs: $([ -n "$SIGN_KEY" ] && echo "release ($(echo "${ROOTS//,/ }" | wc -w | tr -d ' ') committed roots, key list ${KEYS_FLOOR%%:*})" || echo 'development')  signing: $([ -n "$SIGN_KEY" ] && echo yes || echo 'no (drafts)')"
mkdir -p "$OUT/bin" "$OUT/dl"

# ── vet + test every module once, on the host ─────────────────────────────────────────────────────
# relsign signs every release and packaging/trust is what every binary trusts (the stub's and the
# store's verifier, relsign's encoding): both are tested on every run, --only or not.
if [ "$RUN_TESTS" = 1 ]; then
  # dgo's oracles compare it with CPython 3.12's own answers; 3.13 and 3.14 answer some by themselves
  # (argparse, textwrap, json, unicodedata: six tests on 3.14, DGO-1038). Said, not refused.
  pyv="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" || pyv="none"
  [ "$pyv" = 3.12 ] || echo "note: python3 here is $pyv — dgo's oracles answer as CPython 3.12 (go-test.yml pins it), so a parity failure below may be this interpreter's and not dgo's"
  for m in "${MODULES[@]}" "relsign packaging/relsign no" "trust packaging/trust no"; do
    read -r name dir _ <<<"$m"
    [ -z "$ONLY" ] || [ "$ONLY" = "$name" ] || [ "$name" = relsign ] || [ "$name" = trust ] || continue
    echo "--- $name: go vet + go test ($dir)"
    # A pass shows its last lines; a failure shows the run FROM its first failing test or panic (a
    # timeout's names the test before every goroutine's stack) and then every package's line — or the
    # build said FAIL and threw away why (DGO-1040). A build failure has neither: its last lines say it.
    # Not verbose: a verbose run prints a test's reasons before its FAIL line, where this cannot show
    # them. A skipped oracle is go-test.yml's to catch — it runs every push with -v and greps the skips.
    (cd "$REPO/$dir" && CGO_ENABLED=0 go vet ./... && {
      CGO_ENABLED=0 go test ./... >"$WORK/go-test.log" 2>&1 && tail -n 3 "$WORK/go-test.log" || {
        first="$(awk '/^(--- FAIL|panic:)/ {p=1} p' "$WORK/go-test.log" | head -n 150)" || true
        if [ -n "$first" ]; then printf '%s\n' "$first"; grep -E '^(ok|FAIL)[[:space:]]' "$WORK/go-test.log" || true
        else tail -n 200 "$WORK/go-test.log"; fi
        exit 1; }
    })
  done
fi

# ── the console's files, built into dgo ───────────────────────────────────────────────────────────
# The module is copied as it stands — its Go code is the working tree's, as every module's is — and the
# copy's snapshot/ is filled from git: the console the binary serves is a commit's, and commit-time (the
# files' modification time, which the shell's Last-Modified and ETags carry) is that commit's — the same
# in a shallow clone and a full one, so the bytes stay reproducible. -trimpath makes a binary built in
# the copy the very bytes one built in place would be. The copy lives under WORK, so it goes with WORK
# on every way out (a second `trap … EXIT` here would replace WORK's and leak the relsign build again).
DGO_MODULE=""
if [ -z "$ONLY" ] || [ "$ONLY" = dgo ] || [ "$CHECK_REPRO" = 1 ]; then
  CONSOLE_TMP="$WORK/console"; mkdir -p "$CONSOLE_TMP"
  DGO_MODULE="$CONSOLE_TMP/dgo"
  snapshot="$DGO_MODULE/internal/console/snapshot"
  cp -R "$REPO/packaging/dgo" "$DGO_MODULE"
  # dgo's go.mod replaces sibling modules by RELATIVE path (`=> ../trust`). The copy gets the same
  # siblings beside it, so the path resolves and the build info is byte for byte an in-place build's —
  # without them the copy cannot build at all ("replacement directory ../trust does not exist").
  for sib in $(sed -n 's#^replace [^ ]* => \.\./\([A-Za-z0-9._-]*\)$#\1#p' "$REPO/packaging/dgo/go.mod"); do
    cp -R "$REPO/packaging/$sib" "$CONSOLE_TMP/$sib"
  done
  rm -rf "$snapshot" && mkdir -p "$snapshot"
  git -C "$REPO" archive --format=tar HEAD platform-base/console | tar -x -C "$CONSOLE_TMP" \
    || die "the console built into dgo is copied from git at HEAD, and git archive failed — build from a git checkout"
  cp -R "$CONSOLE_TMP/platform-base/console/static" "$CONSOLE_TMP/platform-base/console/modules.yaml" "$snapshot/"
  git -C "$REPO" show -s --format=%ct HEAD > "$snapshot/commit-time"
  echo "  the console built into dgo: platform-base/console at $(git -C "$REPO" rev-parse --short HEAD) —" \
    "$(find "$snapshot/static" -type f | wc -l | tr -d ' ') files of static/ and modules.yaml, commit-time $(cat "$snapshot/commit-time")"
  if [ -n "$(git -C "$REPO" status --porcelain -- platform-base/console/static platform-base/console/modules.yaml)" ]; then
    echo "  note: platform-base/console has uncommitted changes — dgo carries HEAD's files, not them"
  fi
  if [ "$RUN_TESTS" = 1 ]; then
    source_dir="$CONSOLE_TMP/platform-base/console"
    if command -v cygpath >/dev/null 2>&1; then source_dir="$(cygpath -m "$source_dir")"; fi # Git Bash: go wants C:/…
    echo "--- dgo: go vet + the built-in console's proof, under -tags consoleembed (in the copy)"
    (cd "$DGO_MODULE" && CGO_ENABLED=0 go vet -tags consoleembed ./... && DGO_CONSOLE_SOURCE="$source_dir" \
       CGO_ENABLED=0 go test -tags consoleembed -count=1 -run Embedded ./internal/console/ 2>&1 | tail -n 3)
  fi
fi

# ── cross-compile ─────────────────────────────────────────────────────────────────────────────────
# ldflags per module: the version symbol where the binary has one; a release's installer also gets the
# download site and the key list's floor (its roots are roots.txt, embedded — never a flag). dgo is
# built from the copy above, with the console's files.
build_one() { # name dir has_version os arch outfile
  local name="$1" dir="$REPO/$2" hasver="$3" os="$4" arch="$5" outfile="$6" ld="-s -w" tags=""
  [ "$hasver" = yes ] && ld="$ld -X main.version=$VERSION"
  if [ "$name" = dgo-install ] && [ -n "$SIGN_KEY" ]; then
    ld="$ld -X main.siteURL=$BASE_URL -X main.keysFloor=$KEYS_FLOOR"
  fi
  if [ "$name" = dgo ]; then dir="$DGO_MODULE" tags=consoleembed; fi
  (cd "$dir" && CGO_ENABLED=0 GOOS="$os" GOARCH="$arch" GOFLAGS=-buildvcs=false \
     go build -trimpath -tags "$tags" -ldflags "$ld" -o "$outfile" .)
}

built=()
for m in "${MODULES[@]}"; do
  read -r name dir hasver <<<"$m"
  [ -z "$ONLY" ] || [ "$ONLY" = "$name" ] || continue
  extra=""; [ "$name" = dgo ] && extra="$CLI_TARGETS"
  for t in $TARGETS $extra; do
    os="${t%/*}"; arch="${t#*/}"; ext=""; [ "$os" = windows ] && ext=".exe"
    f="$OUT/bin/$name-$os-$arch$ext"
    build_one "$name" "$dir" "$hasver" "$os" "$arch" "$f"
    built+=("$f")
    size="$(wc -c < "$f" | tr -d ' ')"
    printf '  built %-40s %9s bytes\n' "$f" "$size"
    if [ "$name" = dgo-install ] && [ "$size" -gt "$STUB_MAX_BYTES" ]; then
      die "$f is $size bytes — over the stub's budget of $STUB_MAX_BYTES (4 MiB); see packaging/installer/README.md"
    fi
  done
done

# ── reproducibility: the same input twice must be the same bytes ───────────────────────────────────
if [ "$CHECK_REPRO" = 1 ]; then
  tmp="$WORK/repro"; mkdir -p "$tmp"
  build_one dgo packaging/dgo yes linux amd64 "$tmp/a"
  build_one dgo packaging/dgo yes linux amd64 "$tmp/b"
  a="$(sha256_of "$tmp/a")"; b="$(sha256_of "$tmp/b")"; rm -rf "$tmp"
  [ "$a" = "$b" ] || die "NOT reproducible: two builds of dgo linux/amd64 differ ($a vs $b)"
  echo "  reproducible: two builds of dgo linux/amd64 are byte-identical ($a)"
fi

# ── checksums ─────────────────────────────────────────────────────────────────────────────────────
( cd "$OUT/bin" && : > SHA256SUMS && for f in $(ls | grep -v '^SHA256SUMS$' | sort); do
    printf '%s  %s\n' "$(sha256_of "$f")" "$f" >> SHA256SUMS; done )
echo "  wrote $OUT/bin/SHA256SUMS ($(wc -l < "$OUT/bin/SHA256SUMS" | tr -d ' ') files)"

# ── the website's download tree: keys.json, dgo under the installer's name, the manifest it verifies ─
if [ -z "$ONLY" ] || [ "$ONLY" = dgo ]; then
  # The tree is exactly this run's: a manifest left by an earlier run (another key, another --targets)
  # must never be published beside it.
  rm -rf "$OUT/dl" && mkdir -p "$OUT/dl"
  if [ -n "$SIGN_KEY" ]; then cp "$KEYS_JSON" "$OUT/dl/keys.json"; fi
  for t in $TARGETS; do
    os="${t%/*}"; arch="${t#*/}"; ext=""; [ "$os" = windows ] && ext=".exe"
    d="$OUT/dl/$os/$arch"; mkdir -p "$d"
    cp "$OUT/bin/dgo-$os-$arch$ext" "$d/dgo-core$ext"
    set -- -site "$BASE_URL" -version "$VERSION" -target "$t" -url "$BASE_URL/$os/$arch/dgo-core$ext" \
      -file "$d/dgo-core$ext" -expires "$EXPIRES" -min-bootstrapper "$MIN_BOOT"
    if [ -n "$SIGN_KEY" ]; then
      relsign manifest -signer "$SIGN_KEY" "$@" > "$d/manifest.json"
      rm -f "$d/manifest.unsigned.json"
    else
      relsign manifest -unsigned "$@" > "$d/manifest.unsigned.json"
      rm -f "$d/manifest.json"
    fi
  done
  if [ -n "$SIGN_KEY" ]; then
    verify_tree "$OUT/dl" "$BASE_URL" "$VERSION" "$KEYS_FLOOR" || die "the signed tree does not verify by the stub's own rules — nothing here may be published"
    echo "  wrote $OUT/dl/{keys.json, <os>/<arch>/{dgo-core,manifest.json}} — $(echo $TARGETS | wc -w | tr -d ' ') signed manifests; keys.json (against the floor the stubs carry), every manifest and every payload verified by the stub's own rules"
  else
    echo "  wrote $OUT/dl/<os>/<arch>/{dgo-core,manifest.unsigned.json} — UNSIGNED drafts (no --sign-key); the installer refuses these"
  fi
fi

echo "=== done: $VERSION — ${#built[@]} binaries in $OUT/bin, checksums in $OUT/bin/SHA256SUMS"
