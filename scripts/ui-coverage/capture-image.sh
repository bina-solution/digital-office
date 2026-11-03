#!/usr/bin/env bash
# capture-image.sh — the office's ONE browser image, and the one place it is built. Sourced, never run.
#
# `ui-capture` is where Playwright + Chromium are DECLARED for everything that drives a browser
# (scripts/ui-coverage/Dockerfile: `pip install playwright`, apt chromium, UI_CHROME_BIN=/usr/bin/
# chromium). That is the whole declaration — a machine that happens to have playwright installed is
# not it, and a tool that only runs because someone installed one by hand is the bug this file
# exists to prevent. Every driver of a live office therefore runs INSIDE this image, attached to the
# stack network, with the checkout bind-mounted:
#
#   * the ui-map's shards            — run_capture.sh
#   * scripts/remote-ui-capture.py   — the remote-tile QA driver
#   * the flow suite                 — flow-qa.sh (`bbox flow-qa`), against the sim or a live office
#
# The build lives here, once, because a second copy of it is how the two callers drift — and the
# flags below are not decoration: they are the proxy/no-egress accommodations a sandboxed host
# needs, each of which was measured the hard way (see the notes inside).
#
# Source it AFTER scripts/lib.sh — `say`, `npath` and `timeout_bin` come from there. Reads:
#   UI_CAPTURE_IMAGE       image tag (default ui-capture:latest)
#   UI_CAPTURE_BUILD_ARGS  extra `docker build` args (e.g. pip trusted-host behind a proxy)
#   UI_CAPTURE_SKIP_BUILD  1 = use the image already on this engine, never build
#   UI_BUILD_TIMEOUT       build ceiling in seconds (default 600)
# Sets IMAGE to the tag it resolved.
#
# It is SOURCED, but it must not depend on being sourced in the right order: it calls `npath()`,
# which lives in scripts/lib.sh, and an unsourced `npath` expands to nothing under `set -u` —
# a driver binding `""` as its mount source instead of the checkout. Source it itself, once.
command -v npath >/dev/null 2>&1 || {
  . "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/scripts/lib.sh"
}

ensure_capture_image() {
  local label="${1:-capture}"
  IMAGE="${UI_CAPTURE_IMAGE:-ui-capture:latest}"
  local dir; dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [ "${UI_CAPTURE_SKIP_BUILD:-0}" = 1 ] && docker image inspect "${IMAGE}" >/dev/null 2>&1; then
    echo "### ${label} — using prebuilt capture image (${IMAGE})"
    return 0
  fi
  echo "### ${label} — build capture image (${IMAGE})"
  # Build context = the Dockerfile's own dir, NOT the repo root: the Dockerfile has no COPY, so it
  # needs nothing from the tree, and sending the whole repo (data/, .git/, node_modules) as context
  # every run wasted minutes. Drivers are bind-mounted at runtime, not baked in. Layers (apt+pip)
  # are content-addressed, so on the persistent runner the second run onward is a near-instant cache
  # hit. Bounded by `timeout`: a wedged apt/pip download must fail fast, never wedge the whole run
  # for the job's 60-min ceiling the way an un-timed build did.
  local bargs=(${UI_CAPTURE_BUILD_ARGS:-})
  # MITM-proxy sandbox: `bbox run` CA-shadows python:3.12-slim so pip trusts the proxy CA; if a
  # driver is run standalone (base not shadowed), trust pypi directly so `pip install playwright`
  # still succeeds. Also share the host network + pass the proxy build-args so the image's apt-get
  # (chromium + fonts) reaches a strict egress proxy. Empty/absent on a normal host → same as before.
  if command -v ccr_have_proxy_ca >/dev/null 2>&1 && ccr_have_proxy_ca; then
    bargs+=(--build-arg "PIP_TRUSTED=--trusted-host=pypi.org --trusted-host=files.pythonhosted.org")
  fi
  # [2026-08-23] MOVED OUT of the proxy-CA branch. ccr_proxy_build_flags answers TWO questions,
  # and only one of them is about a proxy: it also emits `--network host` for a host whose DEFAULT
  # BRIDGE has no egress, where a build cannot reach deb.debian.org at all. Nesting the call inside
  # `if ccr_have_proxy_ca` meant that on a no-proxy/dead-bridge host the flag was never asked for,
  # and this build died after 481s of:
  #     Err:3 http://deb.debian.org/debian-security trixie-security InRelease
  #       Temporary failure resolving 'deb.debian.org'
  #     ::error::ui-capture image build failed or timed out (600s)
  # which is why `bbox ui-map` produced no capture results. The function is a no-op on a healthy
  # host (empty output, same command as before), so calling it unconditionally costs nothing.
  # Third site with this shape — ccr_build_serial and baseline.sh P2 had the same gate.
  if command -v ccr_proxy_build_flags >/dev/null 2>&1; then
    # shellcheck disable=SC2206 — flags (--network host + --build-arg …) are meant to word-split.
    bargs+=( $(ccr_proxy_build_flags) )
  fi
  local tbin; tbin="$(timeout_bin)"
  ${tbin:+${tbin} --kill-after=30 --signal=KILL ${UI_BUILD_TIMEOUT:-600}} \
    docker build -f "$(npath "${dir}")/Dockerfile" -t "${IMAGE}" "${bargs[@]}" "$(npath "${dir}")" \
    || { echo "::error::ui-capture image build failed or timed out (${UI_BUILD_TIMEOUT:-600}s)"; return 1; }
}
