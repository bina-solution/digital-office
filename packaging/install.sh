#!/usr/bin/env bash
# install.sh — הלשכה הדיגיטלית DGO in one command, for a person or an agent (DGO-1802, 2026-11-10).
# Served at https://digital-office.co.il/install.sh (a copy of this file). It is the git path, for today: once
# signed releases exist, `packaging/installer` (dgo-install, which verifies a signed manifest) is the download,
# and this script hands over to it.
#
#   curl -fsSL https://digital-office.co.il/install.sh | bash                                   # a local office
#   curl -fsSL https://digital-office.co.il/install.sh | DGO_BUSINESS_NAME=MyOffice bash      # Linux, with a domain
#
# It runs exactly the public README's steps and nothing else:
#   git clone → (Linux) ./debian-install.sh → (Linux, named) BUSINESS_NAME in .env → ./bbox run.
# With no name it is a LOCAL office (c0d5a2f33): `DGO_LOCAL=1 ./debian-install.sh` copies no .env, and `./bbox run`
# makes one — every app at <name>.localhost, the console at http://console.localhost (:8080 on a Mac) — and refuses,
# with the reason, where this checkout's office already has containers or volumes.
# Windows has no bash: it prints the guide's three commands for CMD/PowerShell instead.
# Everything is inside main(), called on the last line, so a download cut short runs nothing.
#
# Decided with the release line (2026-11-10): BUSINESS_NAME is written into .env only from DGO_BUSINESS_NAME (a
# server with a domain); the folder is ~/digital-office (DGO_DIR); DGO_REF defaults to the public main until release
# tags exist; serving it from digital-office.co.il is the site lane's.
set -euo pipefail

REPO="https://github.com/bina-solution/digital-office"

say()  { printf '\033[1m[dgo]\033[0m %s\n' "$*"; }
stop() { printf '\033[1m[dgo]\033[0m %s\n' "$*" >&2; exit 1; }

main() {
  local dir="${DGO_DIR:-$HOME/digital-office}" ref="${DGO_REF:-}" os
  os="$(uname -s)"
  case "$os" in
    Linux)  [ -r /etc/debian_version ] || stop "Linux here means Debian or Ubuntu (the guide's only Linux). See $REPO" ;;
    Darwin) ;;
    MINGW*|MSYS*|CYGWIN*)
      say "On Windows the office runs inside WSL. In CMD or PowerShell, in a folder on C:, run:"
      printf '  git clone %s digital-office\n  cd digital-office\n  bbox.cmd install windows\n  bbox.cmd run\n' "$REPO"
      say "Before that, once per machine (as administrator): wsl --install -d Ubuntu, then restart."
      exit 0 ;;
    *) stop "unsupported system: $os (Linux, macOS or Windows). See $REPO" ;;
  esac
  command -v git >/dev/null || stop "git is needed first (Debian/Ubuntu: sudo apt-get install -y git; macOS: xcode-select --install)"

  if [ -d "$dir/.git" ]; then
    say "using the checkout already in $dir"
  elif [ -e "$dir" ]; then
    stop "$dir exists and is not a DGO checkout — set DGO_DIR to another folder"
  else
    say "cloning $REPO into $dir"
    git clone ${ref:+--branch "$ref"} "$REPO" "$dir"
  fi
  cd "$dir"

  if [ "$os" = Linux ]; then
    say "installing what the office needs (Docker 28, pinned) — sudo may ask for your password"
    if [ -n "${DGO_BUSINESS_NAME:-}" ]; then
      case "$DGO_BUSINESS_NAME" in *[!A-Za-z0-9-]*|'') stop "DGO_BUSINESS_NAME: letters, digits and '-' only" ;; esac
      ./debian-install.sh
      grep -q '^BUSINESS_NAME=' .env || stop ".env has no BUSINESS_NAME line — edit it by hand (guide, step 3)"
      sed -i "s/^BUSINESS_NAME=.*/BUSINESS_NAME=${DGO_BUSINESS_NAME}/" .env
      say "BUSINESS_NAME=${DGO_BUSINESS_NAME} written to .env"
    else
      DGO_LOCAL=1 ./debian-install.sh      # no domain: no .env is copied, and ./bbox run makes a local office
      # A checkout older than the local office (c0d5a2f33) ignores DGO_LOCAL and copies the template, whose name
      # was a real office's: never bring an office up on the template's own name — say what to do instead.
      if [ -f .env ] && grep -q '^BUSINESS_NAME=..*' .env \
         && [ "$(grep -m1 '^BUSINESS_NAME=' .env)" = "$(grep -m1 '^BUSINESS_NAME=' .env.ex)" ]; then
        say "this version of DGO has no local office yet, and .env holds the template's own name."
        say "write your business's name on the BUSINESS_NAME line of $dir/.env, then run:  cd $dir && ./bbox run"
        exit 0
      fi
    fi
    if ! id -nG | grep -qw docker && getent group docker | grep -qw "$(id -un)"; then
      say "you were added to the 'docker' group: log out and back in, then run:  cd $dir && ./bbox run"
      exit 0
    fi
  fi

  say "bringing the office up (the first run builds images: 10–15 minutes on a small machine)"
  ./bbox run
  say "done. The first-admin link is in the output above (a line with /setup?code=): open it yourself, and share it with no one."
  # The console's address is the office's own, as its .env declares it after the first run — never written here
  # (G95: a link a person is given is not built by hand; a stranger's office has no hub to build one on).
  local console
  console="$(grep -m1 '^CONSOLE_BASE_URL=' .env 2>/dev/null | cut -d= -f2- | tr -d "\"'")" || true
  [ -n "$console" ] && say "the console, as this office declares it (CONSOLE_BASE_URL in $dir/.env): $console"
  say "the guide: https://digital-office.co.il/docs"
}

main "$@"
