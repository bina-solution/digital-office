#!/usr/bin/env bash
# pip-ensure.sh — make sure a Python package is importable, on hosts where `pip install` refuses.
#
#   scripts/ci/pip-ensure.sh yaml:pyyaml flask pytest
#
# Ubuntu 26.04 (and any PEP 668 distro) marks the system Python as externally managed, so a plain
# `pip install pyyaml` exits 1 with "error: externally-managed-environment" - even when the package
# is ALREADY installed and importable. That turned every CI job that started with `pip install
# pyyaml` into a 0.66-second failure on the self-hosted runner, which read as the platform being
# broken rather than the runner having a newer Ubuntu than the workflow expected.
#
# Each argument is `import_name:pip_name`, or just the name when they match. Already importable ->
# nothing happens. Otherwise try a normal install, then fall back to --break-system-packages, which
# is the same escape hatch scripts/ui-coverage/ui-map.sh already uses.
set -uo pipefail

for spec in "$@"; do
  mod="${spec%%:*}"
  pkg="${spec##*:}"
  if python3 -c "import ${mod}" 2>/dev/null; then
    echo "  ok       ${mod} already importable"
    continue
  fi
  echo "  install  ${pkg}"
  pip install --quiet "${pkg}" 2>/dev/null     || pip install --quiet --break-system-packages "${pkg}" 2>/dev/null     || { echo "  FAILED to install ${pkg}" >&2; exit 1; }
  python3 -c "import ${mod}" 2>/dev/null     || { echo "  installed ${pkg} but ${mod} still does not import" >&2; exit 1; }
done
