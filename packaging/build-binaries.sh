#!/usr/bin/env bash
# build-binaries.sh — the release build of the office's three native binaries, the same on a laptop
# and in CI (.github/workflows/release-binaries.yml runs exactly this).
#
# WHAT IT PRODUCES, under dist/ (git-ignored):
#   bin/dgo-install-<os>-<arch>[.exe]    packaging/installer         the tiny signed bootstrapper (core-007)
#   bin/dgo-<os>-<arch>[.exe]            packaging/dgo               DGO core's CLI (core-005, step 1)
#   bin/forward-auth-<os>-<arch>[.exe]   platform-base/forward-auth  the identity plane (core-006)
#   bin/SHA256SUMS                       one line per file, `sha256sum -c SHA256SUMS` format
#   dl/<os>/<arch>/dgo-core[.exe]        the dgo binary under the NAME the installer downloads
#   dl/<os>/<arch>/manifest.json         {version, payload_url, sha256, sig} — what the website serves and
#                                        the installer verifies (packaging/installer/main.go `manifest`).
#                                        Signed only when --sign-key is given; WITHOUT a key the file is
#                                        manifest.unsigned.json with an empty sig, which the installer
#                                        refuses (fail-closed) — a draft that cannot be mistaken for a release.
#
# WHY ONE SCRIPT. A release is a fact about bytes, not about a machine: the same command here and on the
# runner, so a checksum CI publishes is one anybody can re-derive from the tag on a laptop.
#
# WHY THESE FLAGS. CGO_ENABLED=0 + -trimpath + -buildvcs=false + one pinned Go toolchain = byte-identical
# builds anywhere (--check-reproducible proves it: build twice, compare). -s -w strips the symbol and
# DWARF tables (about a third of the size) and is part of the recipe, not an option. Stdlib-only modules
# mean no go.sum and nothing fetched: `go build` here never touches the network.
#
# SIGNING is packaging/relsign (stdlib Go, crypto/ed25519) — the private half of what the installer
# verifies, over the exact bytes the installer's signedMessage() builds. Nothing but Go is needed; the
# first version signed with openssl and died on Git for Windows' OpenSSL 1.1.1 (no `pkeyutl -rawin`).
# The private key is the OWNER's and is never in this repo:
#   bash packaging/build-binaries.sh --keygen release-key.pem      # once, kept offline (PKCS#8 PEM)
#   bash packaging/build-binaries.sh --pubkey release-key.pem      # the base64 the stub bakes in
# A signed build bakes that public key AND this target's manifest URL into every dgo-install binary, so a
# stub built here trusts exactly one key and asks exactly one URL; then every manifest is verified again
# with the PUBLIC half, the way the installer will, before the script says "done".
#
# USAGE
#   bash packaging/build-binaries.sh [VERSION] [--out DIR] [--targets "os/arch …"] [--only NAME]
#        [--base-url https://digital-office.co.il/dl] [--sign-key KEY.pem] [--check-reproducible] [--no-test]
#   bash packaging/build-binaries.sh --selftest            keygen → sign → verify → tamper-refuse, throwaway key
#   bash packaging/build-binaries.sh --keygen KEY.pem      a new release key (refuses to overwrite)
#   bash packaging/build-binaries.sh --pubkey KEY.pem      print the base64 public key for the stub
# VERSION defaults to 0.0.0-dev+<short sha>; a release passes the tag without its leading v (1.4.0).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
REPO="$(pwd)"

# ── the three modules: name  directory  version-symbol? ───────────────────────────────────────────
MODULES=(
  "dgo-install packaging/installer yes"
  "dgo packaging/dgo yes"
  "forward-auth platform-base/forward-auth no"
)
TARGETS="windows/amd64 windows/arm64 darwin/amd64 darwin/arm64 linux/amd64 linux/arm64"
OUT="dist"
BASE_URL="https://digital-office.co.il/dl"
SIGN_KEY=""
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

# relsign, built once into a temp dir the first time it is needed (a second or two).
RELSIGN=""
relsign() {
  if [ -z "$RELSIGN" ]; then
    need go
    local d; d="$(mktemp -d)"
    RELSIGN="$d/relsign"; [ "$(go env GOOS)" = windows ] && RELSIGN="$RELSIGN.exe"
    (cd "$REPO/packaging/relsign" && CGO_ENABLED=0 go build -trimpath -o "$RELSIGN" .) || die "could not build packaging/relsign"
  fi
  "$RELSIGN" "$@"
}

selftest() {
  local tmp; tmp="$(mktemp -d)"
  relsign keygen "$tmp/key.pem"
  local pub; pub="$(relsign pubkey "$tmp/key.pem")"
  [ "$(printf '%s' "$pub" | base64 -d | wc -c | tr -d ' ')" = "32" ] || die "selftest: public key is not 32 bytes"
  local sha; sha="$(printf 'pretend DGO core' > "$tmp/p"; sha256_of "$tmp/p")"
  local url="https://digital-office.co.il/dl/linux/amd64/dgo-core"
  relsign manifest "$tmp/key.pem" 1.2.0 "$url" "$sha" > "$tmp/manifest.json"
  relsign verify "$pub" "$tmp/manifest.json" >/dev/null || die "selftest: a manifest we just signed does not verify with the public half"
  sed 's/"version":"1.2.0"/"version":"9.9.9"/' "$tmp/manifest.json" > "$tmp/tampered.json"
  if relsign verify "$pub" "$tmp/tampered.json" >/dev/null 2>&1; then die "selftest: a tampered version still verifies"; fi
  rm -rf "$tmp"
  echo "selftest OK — ed25519 keygen, 32-byte public key, signed manifest, verified with the public half, tamper refused"
}

# ── arguments ─────────────────────────────────────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --targets) TARGETS="$2"; shift 2 ;;
    --only) ONLY="$2"; shift 2 ;;
    --base-url) BASE_URL="${2%/}"; shift 2 ;;
    --sign-key) SIGN_KEY="$2"; shift 2 ;;
    --check-reproducible) CHECK_REPRO=1; shift ;;
    --no-test) RUN_TESTS=0; shift ;;
    --selftest) selftest; exit 0 ;;
    --keygen) relsign keygen "$2"; echo "wrote $2 — keep it offline; its public half: $(relsign pubkey "$2")"; exit 0 ;;
    --pubkey) relsign pubkey "$2"; exit 0 ;;
    -h|--help) sed -n '2,41p' "$0"; exit 0 ;;
    -*) die "unknown option $1 (see --help)" ;;
    *) VERSION="$1"; shift ;;
  esac
done
[ -n "$VERSION" ] || VERSION="0.0.0-dev+$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo nogit)"
case "$VERSION" in v*) die "pass the version without its leading v ($VERSION)";; esac

need go
PUB_B64=""
if [ -n "$SIGN_KEY" ]; then
  [ -f "$SIGN_KEY" ] || die "--sign-key $SIGN_KEY: no such file"
  PUB_B64="$(relsign pubkey "$SIGN_KEY")" || die "$SIGN_KEY is not an Ed25519 PKCS#8 key"
fi

echo "=== build-binaries $VERSION  go: $(go version | cut -d' ' -f3)  targets: $TARGETS  signing: $([ -n "$SIGN_KEY" ] && echo yes || echo 'no (drafts)')"
mkdir -p "$OUT/bin" "$OUT/dl"

# ── vet + test every module once, on the host ─────────────────────────────────────────────────────
if [ "$RUN_TESTS" = 1 ]; then
  for m in "${MODULES[@]}" "relsign packaging/relsign no"; do
    read -r name dir _ <<<"$m"
    [ -z "$ONLY" ] || [ "$ONLY" = "$name" ] || [ "$name" = relsign ] || continue
    echo "--- $name: go vet + go test ($dir)"
    (cd "$REPO/$dir" && CGO_ENABLED=0 go vet ./... && CGO_ENABLED=0 go test ./... 2>&1 | tail -n 3)
  done
fi

# ── cross-compile ─────────────────────────────────────────────────────────────────────────────────
# ldflags per module: the version symbol where the binary has one; the installer also gets the public
# key and ITS target's manifest URL when a key is given (a template build otherwise — inert on purpose).
build_one() { # name dir has_version os arch outfile
  local name="$1" dir="$2" hasver="$3" os="$4" arch="$5" outfile="$6" ld="-s -w"
  [ "$hasver" = yes ] && ld="$ld -X main.version=$VERSION"
  if [ "$name" = dgo-install ] && [ -n "$PUB_B64" ]; then
    ld="$ld -X main.pubKeyB64=$PUB_B64 -X main.manifestURL=$BASE_URL/$os/$arch/manifest.json"
  fi
  (cd "$REPO/$dir" && CGO_ENABLED=0 GOOS="$os" GOARCH="$arch" GOFLAGS=-buildvcs=false \
     go build -trimpath -ldflags "$ld" -o "$outfile" .)
}

built=()
for m in "${MODULES[@]}"; do
  read -r name dir hasver <<<"$m"
  [ -z "$ONLY" ] || [ "$ONLY" = "$name" ] || continue
  for t in $TARGETS; do
    os="${t%/*}"; arch="${t#*/}"; ext=""; [ "$os" = windows ] && ext=".exe"
    f="$OUT/bin/$name-$os-$arch$ext"
    build_one "$name" "$dir" "$hasver" "$os" "$arch" "$REPO/$f"
    built+=("$f")
    printf '  built %-40s %6s KB\n' "$f" "$(( $(wc -c < "$f") / 1024 ))"
  done
done

# ── reproducibility: the same input twice must be the same bytes ───────────────────────────────────
if [ "$CHECK_REPRO" = 1 ]; then
  tmp="$(mktemp -d)"
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

# ── the website's download tree: dgo under the installer's name + the manifest it verifies ───────
if [ -z "$ONLY" ] || [ "$ONLY" = dgo ]; then
  for t in $TARGETS; do
    os="${t%/*}"; arch="${t#*/}"; ext=""; [ "$os" = windows ] && ext=".exe"
    d="$OUT/dl/$os/$arch"; mkdir -p "$d"
    cp "$OUT/bin/dgo-$os-$arch$ext" "$d/dgo-core$ext"
    sha="$(sha256_of "$d/dgo-core$ext")"
    url="$BASE_URL/$os/$arch/dgo-core$ext"
    if [ -n "$SIGN_KEY" ]; then
      relsign manifest "$SIGN_KEY" "$VERSION" "$url" "$sha" > "$d/manifest.json"
      rm -f "$d/manifest.unsigned.json"
      relsign verify "$PUB_B64" "$d/manifest.json" >/dev/null || die "$d/manifest.json does not verify with the public half"
    else
      printf '{"version":"%s","payload_url":"%s","sha256":"%s","sig":""}\n' "$VERSION" "$url" "$sha" > "$d/manifest.unsigned.json"
      rm -f "$d/manifest.json"
    fi
  done
  if [ -n "$SIGN_KEY" ]; then
    echo "  wrote $OUT/dl/<os>/<arch>/{dgo-core,manifest.json} — $(echo $TARGETS | wc -w | tr -d ' ') signed manifests, each verified with the public key"
  else
    echo "  wrote $OUT/dl/<os>/<arch>/{dgo-core,manifest.unsigned.json} — UNSIGNED drafts (no --sign-key); the installer refuses these"
  fi
fi

echo "=== done: $VERSION — ${#built[@]} binaries in $OUT/bin, checksums in $OUT/bin/SHA256SUMS"
