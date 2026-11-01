#!/bin/sh
# guest-capture.sh — runs INSIDE the BinaOS distro. Shipped in via /mnt/c and invoked as a file.
#
# WHY A FILE AND NOT AN ARGUMENT
# The path to this code is ssh -> cmd.exe -> wsl.exe -> sh -c, and each hop has its own quoting
# rules. A command with a nested grep pattern in it does not survive the trip: cmd answered
# "' was unexpected at this time." on one hop and sh answered "Unterminated quoted string" on the
# next. Escaping deeper is a losing game - four levels of quoting have no correct answer that stays
# correct when the command changes. Copying a file over and naming it takes no quoting at all.
set -e
# The Windows-side user, passed as a bare argument - a plain word survives every hop untouched,
# which is the whole reason this is a file and not a quoted command.
GUEST_USER="${1:-binaos}"
cd /opt/mapper

echo "--- stack ---"
echo "  containers: $(docker ps --format '{{.Names}}' | wc -l)"

# The mapper composes the strips itself and reads the view profiles as YAML.
python3 -c 'import yaml, PIL' 2>/dev/null || {
  echo "  installing python3-yaml python3-pil"
  apt-get update -qq && apt-get install -y -qq python3-yaml python3-pil >/dev/null 2>&1
}

# UI_CAPTURE_SKIP_BUILD=1 is LOAD-BEARING. Without it run_capture.sh rebuilds the Chromium capture
# image inside this nested VM, alongside 33 running containers, and blows its 600s build timeout.
# The only symptom is "capture produced NO results" - the word "build" appears nowhere. The image is
# identical on every platform, so `uimap-in-guest.sh image` ships the host's prebuilt one instead.
docker image inspect ui-capture:latest >/dev/null 2>&1 || {
  echo "FATAL: ui-capture:latest is not loaded in this distro."
  echo "       Run 'uimap-in-guest.sh image' first - do NOT let the guest build it."
  exit 1
}

UI_MAP_SKIP_SEED=1 UI_MAP_SHARDS=2 UI_CAPTURE_SKIP_BUILD=1 \
  bash scripts/ui-coverage/ui-map.sh > /tmp/uimap.log 2>&1 || true

# Report from the log, not from a tail of the live stream. The capture runs ~900s across several
# phases; `| tail -30` on that stream shows the tail of whichever phase ended last, which is how a
# BUILD timeout came to be read as a CAPTURE failure.
echo "--- outcome ---"
grep -aE 'using prebuilt|wall-time|^views |^ui-map: |captured [0-9]+/' /tmp/uimap.log || {
  echo "no result lines in /tmp/uimap.log - last 15 lines:"
  tail -15 /tmp/uimap.log
  exit 1
}

# Drop the map on the Windows side HERE, while we are already inside the distro with a shell that
# has normal quoting. `fetch` then needs nothing but an scp. Doing this from the outside meant
# sending `sh -c 'cp ... "$(wslpath -a C:/Users/...)"/...'` through cmd.exe, which is the same
# four-layer quoting problem that broke the capture invocation twice.
OUT="/mnt/c/Users/${GUEST_USER}/ui-map-windows.png"
if cp /opt/mapper/ci-artifacts/ui-map/ui-map.png "${OUT}" 2>/dev/null; then
  echo "staged for fetch: ${OUT}  ($(wc -c < "${OUT}") bytes)"
else
  echo "WARNING: no ui-map.png to stage - the capture did not produce one" >&2
fi
