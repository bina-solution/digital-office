#!/usr/bin/env bash
# apparmor-host.sh — the host condition that makes every container's own signals illegal, and the
# one profile that lifts it without weakening the host (DGO-1604). The same profile also lets a
# container ask the desktop's idle monitor one question on a session bus (DGO-1797) — the one way it
# is wider than Docker's own, named in the profile's header («THE ONE WIDENING»).
#
#   bash scripts/apparmor-host.sh status            # what this host does: the label, the signal, the verdict
#   bash scripts/apparmor-host.sh status --machine  # the same in key=value lines (baseline reads this)
#   bash scripts/apparmor-host.sh validate          # parse our profile; loads nothing, needs no root
#   sudo ./bbox apparmor install                    # write it to the host (the OWNER's act)
#   sudo ./bbox apparmor uninstall                  # take it off again
#   bash scripts/apparmor-host.sh verify            # after install: the signal must get through
#
# THE CONDITION. Ubuntu's `kernel.apparmor_restrict_unprivileged_unconfined=1` (its default) makes
# the kernel turn runc's profile change into a STACK, so a container's processes are labelled
# `docker-default//&unconfined` instead of `docker-default`. Docker's profile allows `signal` and
# `ptrace` only to the literal peer `docker-default`, so from kernel 7.0.0-42 (Ubuntu 26.04) a
# container's processes cannot signal each other at all: gosu spins forever at ~80% CPU, `pg_ctl`
# cannot stop a server it started, autovacuum is cancelled every naptime, `pg_reload_conf()` and
# `pg_cancel_backend()` answer "Permission denied", and `docker stop` kills the container because
# tini cannot forward SIGTERM. Measured on the Dell 2026-11-09; the evidence is on work item
# DGO-1604, and the upstream reports it mirrors are moby/moby#54099 and containerd/containerd#14485
# (both open; Launchpad #2172422 is the kernel-side one).
#
# THE FIX is containerd#14487's: the SAME profile may reach its own stacked form, and nothing wider for
# the signals (packaging/linux/apparmor/docker-default.dgo; its two dbus lines are DGO-1797's, named there). It is NOT `kernel.apparmor_restrict_unprivileged_
# unconfined=0` and NOT `apparmor=unconfined` — the host keeps its hardening and the container keeps
# a real profile. Loading a profile is a host policy change, so it is never automatic: install is
# run by the owner, and `bbox baseline` names the condition on a host that has it.
#
# install also writes the profile to /etc/apparmor.d/docker-default, so the fix survives a REBOOT
# (`apparmor.service` loads that directory at boot, and dockerd leaves a profile of that name alone
# when one is already loaded) — a load without that file evaporates at the next boot, silently.
#
# The probe is TWO facts in ONE throwaway container, from an image already on the host, removed at
# once, with no network: the label the process carries, and whether one process of the container can
# signal another (`kill -TERM` to a sibling) — the minimal form of everything above. It touches
# nothing of the office: no volume, no network, no office container.
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SELF_DIR}/.." && pwd)"
PROFILE="${REPO_ROOT}/packaging/linux/apparmor/docker-default.dgo"
#: Where a loaded profile SURVIVES a reboot. install puts it here; uninstall takes it away.
INSTALLED=/etc/apparmor.d/docker-default
#: The engine generation this copy of the template was rendered against. A far newer engine may
#: deny a socket family this copy does not (see the profile's header), so install stops rather
#: than quietly relaxing the host — `--force` is the way past, with the reason written down.
TEMPLATE_MAX_ENGINE_MAJOR="${BBOX_APPARMOR_MAX_ENGINE:-30}"
. "${SELF_DIR}/lib.sh" 2>/dev/null || { ok() { echo "$*"; }; warn() { echo "! $*"; }; bad() { echo "x $*"; }; }
die() { echo "[apparmor] error: $*" >&2; exit 1; }

PROBE_IMAGE="${BBOX_APPARMOR_PROBE_IMAGE:-alpine:latest}"

# ── the two facts ────────────────────────────────────────────────────────────────────────────
# Printed by the probe container: the label on line 1, then SIGNAL=ok|denied|unknown.
probe() {
  docker info >/dev/null 2>&1 || { echo "PROBE=no-docker"; return 0; }
  if ! docker image inspect "${PROBE_IMAGE}" >/dev/null 2>&1; then
    # AA_PULL=1 lets a caller fetch the probe image; the default is OFF, so a caller on a bring-up
    # path bounds its own time instead of hanging on a pull. `bbox run` passes it with a 20 s cap
    # (it pulls far more in the same run), `bbox baseline` with the default, and `status` always.
    [ "${AA_PULL:-0}" = 1 ] || { echo "PROBE=no-image"; return 0; }
    timeout "${AA_PULL_TIMEOUT:-90}" docker pull -q "${PROBE_IMAGE}" >/dev/null 2>&1 || { echo "PROBE=no-image"; return 0; }
  fi
  # `-k 5 12`: a container whose signals are ALL denied can wedge on its own child; bounded twice.
  # `--network none`: this probe reads a label and sends one signal; it needs no network at all.
  timeout -k 5 12 docker run --rm --pull never --network none --init "${PROBE_IMAGE}" sh -c '
    cat /proc/self/attr/current 2>/dev/null || echo "label-unknown"
    ( sleep 30 ) & p=$!
    sleep 1
    # A POSITIVE CONTROL, so a missing `sleep` never reads as a denied signal: the child is there
    # (/proc needs no signal), and only a real refusal counts as a refusal.
    [ -d "/proc/$p" ] || { echo "SIGNAL=unknown"; exit 0; }
    if msg=$(kill -TERM "$p" 2>&1); then echo "SIGNAL=ok"
    elif printf "%s" "$msg" | grep -qi "permission"; then echo "SIGNAL=denied"
    else echo "SIGNAL=error:$msg"; fi
    exit 0' 2>/dev/null || echo "PROBE=failed"
}

# label=stacked|plain|unconfined|none|unknown · signal=ok|denied|unknown · verdict=broken|traded|ok|unknown
facts() {
  local out label label_ signal verdict reason=""
  out="$(probe)"
  case "${out}" in
    *PROBE=no-docker*) echo "label=unknown signal=unknown verdict=unknown reason=no-docker"; return 0 ;;
    *PROBE=no-image*)  echo "label=unknown signal=unknown verdict=unknown reason=no-probe-image"; return 0 ;;
    *PROBE=failed*)    echo "label=unknown signal=unknown verdict=unknown reason=probe-failed"; return 0 ;;
  esac
  label="$(printf '%s\n' "${out}" | head -1)"
  case "${label}" in
    *"//&"*)                   label_="stacked" ;;
    docker-default*)           label_="plain" ;;
    *unconfined*)              label_="unconfined" ;;   # a container with no profile, by choice
    label-unknown*)            label_="none" ;;         # this kernel has no AppArmor at all
    *)                         label_="other" ;;
  esac
  signal="$(printf '%s\n' "${out}" | sed -n 's/^SIGNAL=\(ok\|denied\).*$/\1/p' | head -1)"
  case "${out}" in
    *SIGNAL=error:*) reason="probe-error:$(printf '%s' "${out}" | sed -n 's/.*SIGNAL=error:\(.*\)/\1/p' | head -1)" ;;
    *SIGNAL=unknown*) reason="no-sibling-to-signal" ;;
  esac
  [ -n "${signal}" ] || signal="unknown"
  # The condition this item is about: the label is stacked AND the signal does not get through.
  # A stacked label whose signals DO get through is a host that is already fixed (or one running our
  # profile) — a different sentence, never the same verdict.
  if [ "${label_}" = "stacked" ] && [ "${signal}" = "denied" ]; then verdict="broken"
  elif [ "${label_}" = "unconfined" ] && [ "${signal}" = "ok" ]; then verdict="traded"
  elif [ "${label_}" = "none" ] && [ "${signal}" = "ok" ]; then verdict="ok"; reason="no-apparmor"
  elif [ "${signal}" = "ok" ]; then verdict="ok"
  else verdict="unknown"; reason="${reason:-unreadable-signal}"; fi
  echo "label=${label_} signal=${signal} verdict=${verdict}${reason:+ reason=${reason}} raw_label=${label% (enforce)}"
}

say_facts() {
  local f; f="$(facts)"
  local label signal verdict raw reason
  # `(^| )` so the FIRST field is matched too: the machine line starts with `label=`.
  pick() { printf '%s\n' "$1" | grep -oE "(^| )$2=[^ ]*" | head -1 | sed "s/.*$2=//"; }
  label="$(pick "${f}" label)"; signal="$(pick "${f}" signal)"
  verdict="$(pick "${f}" verdict)"; raw="$(printf '%s\n' "${f}" | sed -n 's/.*raw_label=//p')"
  reason="$(pick "${f}" reason)"
  case "${label}" in
    stacked)    echo "  container label : ${raw}   (the kernel stacks runc's profile change)" ;;
    plain)      echo "  container label : ${raw}   (not stacked — this host does not have the condition)" ;;
    unconfined) echo "  container label : ${raw}   (containers run with NO profile — the hardening was traded away)" ;;
    none)       echo "  container label : no AppArmor mediation on this kernel (nothing here is AppArmor's doing)" ;;
    *)          echo "  container label : could not be read" ;;
  esac
  case "${signal}" in
    ok)     echo "  in-container signal : one process signalled its sibling (kill -TERM got through)" ;;
    denied) echo "  in-container signal : DENIED — a process cannot signal its sibling in the same container" ;;
    *)      echo "  in-container signal : could not be measured${reason:+ (${reason})}" ;;
  esac
  echo "  ptrace : covered by the same rule; not measured here (a ptrace denial is what makes a tool"
  echo "           that reads another process's memory fail with EPERM)"
  case "${verdict}" in
    broken)
      echo
      warn "this host cannot run a database in a container, and no error says why: gosu spins forever"
      warn "at ~80% CPU, autovacuum is cancelled, pg_reload_conf()/pg_cancel_backend() answer"
      warn "Permission denied, and docker stop kills the container (tini cannot forward SIGTERM)."
      echo "  fix (a host policy change, the owner's act; it does not weaken the host):"
      echo "      sudo ./bbox apparmor install"
      echo "  check it first without touching anything:  ./bbox apparmor validate" ;;
    traded)
      warn "this host runs containers with NO AppArmor profile at all (apparmor=unconfined): it works,"
      warn "and the host's hardening was traded away for it. That is a decision for a given host,"
      warn "never a product default — ./bbox apparmor install is the way back to a real profile." ;;
    ok)
      [ "${label}" = "stacked" ] && echo "  verdict : the stacked label is present and signals get through — nothing to do" \
                                  || echo "  verdict : this host is fine" ;;
    *)
      echo "  verdict : undetermined — the probe could not answer (see $0 status --machine)" ;;
  esac
}

case "${1:-status}" in
  status)
    export AA_PULL="${AA_PULL:-1}"   # a deliberate read may fetch the probe image; `check` may not
    if [ "${2:-}" = "--machine" ]; then facts; exit 0; fi
    echo "apparmor on $(hostname):"
    say_facts
    if [ -f "${INSTALLED}" ]; then
      echo "  our profile : ${INSTALLED} (loaded at every boot; install put it there)"
    else
      echo "  our profile : not installed here (no ${INSTALLED})"
    fi
    exit 0 ;;

  # For a caller that must decide: 0 = this host is fine, 1 = the condition is present, 2 = unknown.
  check)
    v="$(facts | sed -n 's/.*verdict=\([a-z]*\).*/\1/p' | head -1)"
    case "${v}" in ok|traded) exit 0 ;; broken) exit 1 ;; *) exit 2 ;; esac ;;

  validate)
    command -v apparmor_parser >/dev/null 2>&1 || die "apparmor_parser is not on this host — AppArmor is not in use here"
    [ -r "${PROFILE}" ] || die "profile missing: ${PROFILE}"
    # abi/3.0 is shipped by apparmor itself; a host without it cannot be given this profile at all.
    [ -r /etc/apparmor.d/abi/3.0 ] || die "this host has no /etc/apparmor.d/abi/3.0 — its AppArmor is older than the profile needs"
    # -Q: parse only, never touch the kernel. -T: do not write the parser cache.
    if apparmor_parser -QT "${PROFILE}"; then
      ok "profile parses: $(basename "${PROFILE}") — nothing was loaded"
    else
      die "the profile does not parse (see the parser's own sentence above)"
    fi
    exit 0 ;;

  verify)
    export AA_PULL="${AA_PULL:-1}"
    f="$(facts)"; v="$(printf '%s\n' "${f}" | sed -n 's/.*verdict=\([a-z]*\).*/\1/p' | head -1)"
    s="$(printf '%s\n' "${f}" | sed -n 's/.* signal=\([a-z]*\).*/\1/p' | head -1)"
    if [ "${s}" = "ok" ]; then ok "the signal gets through (verdict=${v})"; exit 0; fi
    bad "the signal still does not get through (verdict=${v}) — read: journalctl -k | grep DENIED | tail"; exit 1 ;;

  install)
    export AA_PULL="${AA_PULL:-1}"
    [ "$(id -u)" = 0 ] || die "installing an AppArmor profile changes this host's policy — run it with sudo: sudo ./bbox apparmor install"
    command -v apparmor_parser >/dev/null 2>&1 || die "apparmor_parser is not on this host — nothing to install"
    bash "${BASH_SOURCE[0]}" validate >/dev/null || die "the profile does not validate — not loading it"
    engine="$(docker version --format '{{.Server.Version}}' 2>/dev/null | cut -d. -f1)"
    if [ -n "${engine}" ] && [ "${engine}" -gt "${TEMPLATE_MAX_ENGINE_MAJOR}" ] 2>/dev/null; then
      [ "${2:-}" = "--force" ] || die "this engine is ${engine}.x and this profile was rendered against an older template: an engine that denies MORE socket families than this copy names would be quietly relaxed by loading it. Re-render packaging/linux/apparmor/docker-default.dgo from that engine's template, or pass --force with the reason on the item."
    fi
    v="$(facts | sed -n 's/.*verdict=\([a-z]*\).*/\1/p' | head -1)"
    case "${v}" in
      broken) : ;;
      ok|traded)
        if [ "${2:-}" != "--force" ]; then
          say_facts
          ok "this host does not have the condition, so nothing was changed (--force loads it anyway)"
          exit 0
        fi ;;
      *)
        # A measurement that did not happen is NOT "no condition": say which, and touch nothing.
        die "the host could not be measured ($(facts | sed -n 's/.*reason=//p' | head -1)), so this cannot tell whether it needs the profile. Nothing was changed. Measure it: ./bbox apparmor status" ;;
    esac
    install -D -m 0644 "${PROFILE}" "${INSTALLED}" || die "could not write ${INSTALLED}"
    # apparmor.service loads this directory at boot, and dockerd leaves a profile of that name alone
    # when one is already loaded — so the NAME in this file is what survives, not the path.
    apparmor_parser -r "${INSTALLED}" || die "apparmor_parser -r refused the profile (see above)"
    if bash "${BASH_SOURCE[0]}" verify; then
      ok "loaded docker-default from ${INSTALLED} — Docker's rules plus the stacked peer, and the desk's one question on a session bus (DGO-1797)"
      echo "  it survives a reboot: apparmor.service loads ${INSTALLED} before the engine starts"
      warn "containers that are ALREADY RUNNING keep the rules they started with — recreate them"
      warn "(./bbox run does); otherwise the hung ones stay hung."
      echo "  undo:  sudo ./bbox apparmor uninstall"
    else
      bad "the profile loaded but the signal still does not get through — the kernel may be logging a"
      bad "different denial; read: journalctl -k | grep DENIED | tail"
      echo "  undo:  sudo ./bbox apparmor uninstall"
      exit 1
    fi
    exit 0 ;;

  uninstall)
    [ "$(id -u)" = 0 ] || die "removing a host profile needs root: sudo ./bbox apparmor uninstall"
    if [ ! -f "${INSTALLED}" ] && [ "${2:-}" != "--force" ]; then
      die "there is no ${INSTALLED} on this host, so the loaded docker-default is not ours — removing it would take the engine's own profile away. Nothing was changed (--force does it anyway)."
    fi
    apparmor_parser -R "${INSTALLED}" || warn "apparmor_parser -R reported a problem (see above)"
    rm -f "${INSTALLED}"
    warn "removed. A container started now names a docker-default that is not loaded, until the engine"
    warn "reloads its own: restart it now — sudo systemctl restart docker."
    exit 0 ;;

  *) die "unknown verb '$1' (status | status --machine | check | validate | verify | install | uninstall)" ;;
esac
