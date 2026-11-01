#!/usr/bin/env bash
# engine.sh — the PROJECT ENGINE on macOS: start/stop/inspect the Lima/vz guest that runs Docker 28.
#
#   ./bbox engine start        boot the engine (first run: fetch Lima, download the guest image,
#                              install Docker CE 28.5.2 pinned — ~5 min on a normal line)
#   ./bbox engine stop         stop the guest (images/volumes/containers persist on its disk)
#   ./bbox engine status       one line: Running / Stopped / not created
#   ./bbox engine shell [cmd]  a root shell in the guest, cwd = this repo
#   ./bbox engine socket       print the host-side path of the engine's docker socket
#   ./bbox engine doctor       versions, sizing, paths, and whether the pair tunnel's UDP port is
#                              forwarded — what to paste into an issue
#   ./bbox engine forwards [status|--apply]   the pair tunnel's UDP forward: is this office dialable,
#                              and apply the template's rule to an engine created without it
#                              (STOPS the office and boots it again — run it from the Mac itself)
#   ./bbox engine power [status|start|stop]   the Mac-side keep-awake agent (policy: console settings)
#   ./bbox engine destroy --force   delete the guest and EVERYTHING in it (images, volumes)
#
# `./bbox <anything else>` on macOS is handed here as `engine.sh exec -- ./bbox …` by bbox itself
# and runs INSIDE the guest as root, cwd = the same repo path — the exact shape of bbox.cmd → WSL
# on Windows. One checkout, one engine, no Docker Desktop.
#
# Everything this creates lives under ~/.bbox/macos (Lima binaries + LIMA_HOME with the VM disk);
# nothing is written outside it or the repo, and no step needs admin.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"
TEMPLATE="${HERE}/engine.yaml"

BBOX_MACOS_HOME="${BBOX_MACOS_HOME:-${HOME}/.bbox/macos}"
# A private LIMA_HOME: the user's own Lima/Colima instances (if any) are never listed, touched or
# confused with ours, and `rm -rf ~/.bbox/macos` removes the whole engine in one go.
export LIMA_HOME="${LIMA_HOME:-${BBOX_MACOS_HOME}/lima}"
INSTANCE="${BBOX_VM_NAME:-bbox}"

c1=$'\033[36m'; cg=$'\033[32m'; cy=$'\033[33m'; cr=$'\033[31m'; c0=$'\033[0m'
say() { echo "${c1}[bbox engine]${c0} $*"; }
ok()  { echo "  ${cg}ok${c0}   $*"; }
die() { echo "${cr}[bbox engine] error:${c0} $*" >&2; exit 1; }

[ "$(uname -s)" = Darwin ] || die "this is the macOS engine; on Linux/WSL bbox talks to dockerd directly"

LIMACTL=""
ensure_runtime() {
  bash "${HERE}/fetch-runtime.sh" >&2
  LIMACTL="$(bash "${HERE}/fetch-runtime.sh" --print)"
  [ -x "${LIMACTL}" ] || die "limactl not found at ${LIMACTL}"
}
lima() { "${LIMACTL}" "$@"; }

# ── sizing ───────────────────────────────────────────────────────────────────────────────────
# The guest is the docker host, so its memory is what platform/profiles/perf-profiles.yml
# measures (`requires.mem`), exactly as the WSL VM is on Windows. The floor profile (ci-small)
# needs 5 GiB, so on an 8 GB Mac the guest gets 5 and macOS keeps 3 — tight, and deliberate: the
# alternative is a guest that satisfies no profile at all. Larger hosts hand over 60%, capped.
# Override any of these with BBOX_VM_MEM (GiB), BBOX_VM_CPUS, BBOX_VM_DISK (GiB).
host_mem_gib() { echo $(( $(sysctl -n hw.memsize) / 1073741824 )); }
vm_mem()  { if [ -n "${BBOX_VM_MEM:-}" ]; then echo "${BBOX_VM_MEM}"; else local h; h="$(host_mem_gib)"; if [ "${h}" -le 8 ]; then echo 5; else local m=$(( h * 60 / 100 )); [ "${m}" -gt 12 ] && m=12; echo "${m}"; fi; fi; }
vm_cpus() { if [ -n "${BBOX_VM_CPUS:-}" ]; then echo "${BBOX_VM_CPUS}"; else local n; n="$(sysctl -n hw.ncpu)"; [ "${n}" -gt 4 ] && n=4; echo "${n}"; fi; }
vm_disk() { echo "${BBOX_VM_DISK:-60}"; }

# Rosetta lets the guest run linux/amd64 images that have no arm64 build. It is Apple's, not
# ours to ship, and installing it is an admin step (`softwareupdate --install-rosetta`). So: use
# it when present, say so when absent, never require it.
rosetta_flags() {
  if [ -f /Library/Apple/usr/share/rosetta/rosetta ] && arch -x86_64 /usr/bin/true 2>/dev/null; then
    printf '%s' "--set=.vmOpts.vz.rosetta.enabled=true | .vmOpts.vz.rosetta.binfmt=true"
  fi
}

state() {   # Running | Stopped | Broken | … | "" (not created)
  lima list --format '{{.Name}} {{.Status}}' 2>/dev/null | awk -v n="${INSTANCE}" '$1==n {print $2}'
}
host_socket() { printf '%s/%s/sock/docker.sock\n' "${LIMA_HOME}" "${INSTANCE}"; }

cmd_start() {
  ensure_runtime
  local st; st="$(state)"
  case "${st}" in
    Running) ok "engine already running"; return 0 ;;
    "")
      say "creating the engine: Ubuntu 24.04 + Docker 28.5.2, $(vm_cpus) cpus / $(vm_mem) GiB / $(vm_disk) GiB disk (host has $(sysctl -n hw.ncpu) cores, $(host_mem_gib) GiB)"
      local rs; rs="$(rosetta_flags)"
      [ -n "${rs}" ] && ok "Rosetta present — amd64 images will run too" || say "${cy}Rosetta not installed — only arm64 images will run (optional: softwareupdate --install-rosetta)${c0}"
      # --mount "$HOME:w": the repo is under the user's home and must appear at the SAME path in
      # the guest (compose bind-mounts ${REPO_ROOT}/… and dockerd resolves them in-guest). Mounting
      # the home, not the repo, also sidesteps a checkout directory with spaces/non-ASCII in its
      # name — the mount point is then a plain path and the checkout is just a subdirectory of it.
      case "${REPO_ROOT}" in "${HOME}"/*) ;; *) die "the repo must live under ${HOME} to be visible in the guest (it is at ${REPO_ROOT})" ;; esac
      # shellcheck disable=SC2086
      lima start --name="${INSTANCE}" --tty=false \
        --cpus="$(vm_cpus)" --memory="$(vm_mem)" --disk="$(vm_disk)" \
        --mount="${HOME}:w" ${rs:+"${rs}"} "${TEMPLATE}" \
        || die "the engine did not come up. Diagnose: ${LIMACTL} --debug start ${INSTANCE}   (LIMA_HOME=${LIMA_HOME})" ;;
    *)
      say "starting the engine (${st})…"
      lima start --tty=false "${INSTANCE}" || die "the engine did not start. Diagnose: ${LIMACTL} --debug start ${INSTANCE}" ;;
  esac
  # The template's probe already waited for dockerd; prove it from here once more, in one line.
  local v; v="$(lima shell "${INSTANCE}" sudo docker version --format '{{.Server.Version}}' 2>/dev/null || true)"
  [ -n "${v}" ] || die "engine is up but dockerd does not answer inside it"
  ok "project engine: Docker ${v}  socket: $(host_socket)"
  power_agent_start
}

# ── the power agent: keeps the Mac awake while the office should be working ────────────────────
# A sleeping Mac freezes the VM and every agent in it (measured 2026-09-29: the Mac idle-slept ~7 s
# after the display went off, and the running agents spent 28 of 43 hours frozen). The owner sets
# per situation (screen locked, lid closed; on power / on battery) what the office does, in the
# console's settings view; power-agent.py enforces it on the host. One per Mac, tied to the
# engine's host-agent PID: it releases everything and exits when the engine stops.
# BBOX_POWER_AGENT=0 turns it off.
POWER_PID="${BBOX_MACOS_HOME}/power-agent.pid"
POWER_LOG="${BBOX_MACOS_HOME}/power-agent.log"
power_agent_running() { local p; p="$(cat "${POWER_PID}" 2>/dev/null || true)"; [ -n "${p}" ] && kill -0 "${p}" 2>/dev/null; }
power_agent_start() {
  [ "${BBOX_POWER_AGENT:-1}" = 0 ] && return 0
  power_agent_running && return 0
  local ha; ha="$(cat "${LIMA_HOME}/${INSTANCE}/ha.pid" 2>/dev/null || true)"
  [ -n "${ha}" ] && kill -0 "${ha}" 2>/dev/null || return 0
  nohup /usr/bin/python3 "${HERE}/power-agent.py" --repo "${REPO_ROOT}" --watch-pid "${ha}" \
    >>"${POWER_LOG}" 2>&1 </dev/null &
  echo $! > "${POWER_PID}"
  ok "power agent running — the office's sleep/lid policy is in the console → הגדרות מסוף" >&2
}
power_agent_stop() {
  local p; p="$(cat "${POWER_PID}" 2>/dev/null || true)"
  [ -n "${p}" ] && kill "${p}" 2>/dev/null || true   # SIGTERM: it releases what it holds first
  rm -f "${POWER_PID}"
}
cmd_power() {
  case "${1:-status}" in
    start)  ensure_runtime; power_agent_start ;;
    stop)   power_agent_stop; ok "power agent stopped; the Mac sleeps as macOS decides" ;;
    status)
      power_agent_running && ok "power agent: running (pid $(cat "${POWER_PID}"))" || say "power agent: not running"
      /usr/bin/python3 - "${REPO_ROOT}/data/power/status.json" <<'PY' || true
import json, sys, time
try: s = json.load(open(sys.argv[1]))
except Exception: sys.exit(0)
e, p, l = s["effective"], s["power"], s["lid"]
print("  %ss ago · on %s %s%% · lid %s · locked %s · thermal %s" % (int(time.time() - s["updated_at"]), p["source"], p["percent"],
      "closed" if l["closed"] else "open", s["screen_locked"], s["thermal"]["name"]))
print("  screen lock/display off → %s · lid closed → %s%s" % (e["lock"], e["lid"], "" if s["lid_permission"] else " (one-time admin rule not installed)"))
if e["guards"]: print("  guards: " + ", ".join(e["guards"]))
PY
      ;;
    *) die "usage: bbox engine power [status|start|stop]" ;;
  esac
}

# ── what the guest cannot see about its own machine (the pairing contract's "engine's half") ────
# Two facts live on the Mac and nowhere else: its LAN address, and whether this engine really
# forwards the pair tunnel's UDP port into the guest. bbox hands both across in the same
# `limactl shell` every command already goes through, and only when BOTH hold: the guest then
# declares the office as dialable (apps/dgo-extend/hooks/prepare). Without them it stays
# `engine-guest` — a guest that claims an address nothing routes to is worse than one that says it
# can only dial (ai/context/dgo-pairing-contract.md §C).
lan_addr() {   # this Mac's LAN IPv4 — the interface its default route uses, never a guess
  local iface
  iface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
  [ -n "${iface}" ] || return 0
  ipconfig getifaddr "${iface}" 2>/dev/null || true
}

# A deliberately narrow reader for `portForwards`, asked ONE question: which UDP rules are bound to a
# wildcard host address (a peer on the network can reach those; the default `127.0.0.1` it cannot).
# Lima writes the block flat (`- guestPort: 51830` + two-space `key: value`), so this reads no YAML
# beyond that shape, and when it cannot tell it prints NOTHING — "nothing is forwarded" is the safe
# answer, because it leaves the guest on the dial-only path instead of declaring an unreachable
# address. The instance's own lima.yaml is read (not the template): that is what is in effect NOW,
# and the two differ until `bbox engine forwards --apply` has run.
ports_yaml() {   # <file> <ports|json>
  [ -f "${1:-}" ] || return 0
  /usr/bin/python3 - "${1}" "${2}" <<'PY'
import json, re, sys
path, mode = sys.argv[1], sys.argv[2]
rules, cur, inside = [], None, False
for line in open(path, encoding="utf-8"):
    line = line.rstrip("\n")
    if re.match(r"^[A-Za-z_]", line):              # a new top-level key ends the block
        if inside:
            break
        inside = line.startswith("portForwards:")
        continue
    if not inside:
        continue
    m = re.match(r"^\s*-\s*([\w-]+):\s*(.*)$", line)          # a new rule
    if m:
        cur = {m.group(1): m.group(2).strip()}
        rules.append(cur)
        continue
    m = re.match(r"^\s+([\w-]+):\s*(.*)$", line)             # one more key on the current rule
    if m and cur is not None:
        cur[m.group(1)] = m.group(2).strip()

def val(rule, key):
    return str(rule.get(key, "")).strip().strip('"').strip("'")

udp = [r for r in rules
       if val(r, "proto").lower() in ("udp", "any")
       and val(r, "hostIP") not in ("", "127.0.0.1", "localhost", "::1")]
udp = [r for r in udp if val(r, "guestPort").isdigit()]
if mode == "json":
    print(json.dumps([{"proto": val(r, "proto").lower() or "udp",
                       "guestPort": int(val(r, "guestPort")),
                       "hostPort": int(val(r, "hostPort") or val(r, "guestPort")),
                       "hostIP": val(r, "hostIP")} for r in udp]))
else:
    print(" ".join(val(r, "guestPort") for r in udp))
PY
}

instance_ports()  { ports_yaml "${LIMA_HOME}/${INSTANCE}/lima.yaml" ports; }
instance_udp_json() { ports_yaml "${LIMA_HOME}/${INSTANCE}/lima.yaml" json; }
template_udp_json() { ports_yaml "${TEMPLATE}" json; }

# The chain is three links, owned by three places, and they close IN ORDER — this order is the whole
# reason nothing here may gate on the last one:
#   1. the INSTANCE declares the rule        engine.yaml → this Mac's lima.yaml (`forwards --apply`)
#   2. the GUEST listens on that UDP port    dgo-net's docker-proxy, once `.env` publishes it —
#                                            written by dgo-extend's hook, which needs the handoff
#   3. the MAC holds the socket              Lima creates it from the guest's port EVENT
#                                            (hostagent.go: only `static: true` rules are bound at
#                                            startup, and those go through `forwardTCP` — TCP only)
# So handing over the two facts only AFTER link 3 exists would be a closed loop: no handoff → the hook
# declares nothing → nothing in the guest listens → Lima never opens the socket → no handoff. A fresh
# Mac would stay `engine-guest` forever. The handoff therefore requires links 1 and 2 of the DECISION
# (the rule is declared, the Mac has an address to hand over) and never the socket; the socket stays a
# MEASUREMENT, reported by `forward_report` and by the note after a Mac `bbox run`.
udp_listening() {   # <port> → 0 when a UDP socket for it is bound beyond loopback on THIS Mac
  [ -n "${1:-}" ] || return 1
  lsof -nP -iUDP:"${1}" 2>/dev/null | awk -v want=":${1}" '
    NR > 1 && index($9, want) && $9 !~ /^(127\.|localhost|\[::1\])/ { held = 1 }
    END { exit(held ? 0 : 1) }'
}

guest_udp_bound() {   # <port> → 0 when something IN THE GUEST is listening on that UDP port
  [ -n "${1:-}" ] || return 1
  [ "$(state)" = Running ] || return 1
  # `ss -lunH`: one line per socket, the LOCAL address in the 4th field (`0.0.0.0:51830`) and the
  # peer column after it — matched as "the port, then whitespace" so a peer address can never satisfy
  # it and neither can a header row.
  lima shell "${INSTANCE}" -- ss -lunH 2>/dev/null | grep -qE "[:.]${1}[[:space:]]"
}

env_value() {   # <NAME> → the last value of that key in the mounted .env (host side, no guest)
  # `|| true`: a key that is not there yet is the NORMAL case (the office has not published anything
  # on its first run), and under `set -e` + `pipefail` a grep that finds nothing would abort the verb.
  [ -f "${REPO_ROOT}/.env" ] || return 0
  grep -E "^[[:space:]]*${1}[[:space:]]*=" "${REPO_ROOT}/.env" 2>/dev/null | tail -1 |
    sed "s/^[^=]*=//; s/[\"']//g; s/[[:space:]]*$//" || true
}

guest_udp_handoff() {   # → "ADDR PORT" when this engine forwards a UDP port from the Mac's LAN
  local addr port
  addr="$(lan_addr)"
  port="$(instance_ports | awk '{print $1}')"
  [ -n "${addr}" ] && [ -n "${port}" ] || return 0
  printf '%s %s\n' "${addr}" "${port}"
}

# The one expression for "what this engine hands to the guest", so both doors below cannot drift.
handoff_env() {
  local h; h="$(guest_udp_handoff)"
  [ -n "${h}" ] && printf 'BBOX_HOST_LAN_ADDR=%s BBOX_HOST_UDP_PORT=%s' "${h%% *}" "${h##* }"
  return 0
}

# ONE hand-off line for every door into the guest (`bbox …` and an interactive shell), so the two
# cannot drift. `udp_env` is read from the caller's scope (bash scopes locals dynamically) — empty
# whenever this engine has no UDP port to hand over.
guest_shell() {   # shellcheck disable=SC2086
  "${LIMACTL}" shell --workdir "${REPO_ROOT}" "${INSTANCE}" -- \
    sudo --preserve-env=OVERLAYS,BBOX_DOCKER_HOST,BBOX_WITH_BROWSER42,FORCE,PERFORMANCE_PROFILE \
      env BBOX_IN_GUEST=1 ${udp_env} "$@"
}

# After the one command that can DECLARE the tunnel's published port (.env, written inside the guest
# by dgo-extend's prepare hook): look at both halves, and name the open link of the chain only when
# one is open. A warning here has to be true — "declared but the Mac holds nothing" is the NORMAL
# state until the guest listens (dgo-net recreated with the published port), and blaming the firewall
# for that is how a fresh Mac gets sent to look at the wrong thing.
post_run_udp_note() {
  local port; port="$(env_value DGO_WG_PUBLISH_PORT)"
  [ -n "${port}" ] || return 0
  udp_listening "${port}" && return 0
  say "${cy}.env now declares ${port}/udp, and the Mac holds no socket for it yet.${c0}"
  if guest_udp_bound "${port}"; then
    say "  the guest IS listening, so this is a real fault — two candidates, in this order:"
    say "    1. macOS incoming-connection consent denied: System Settings → Network → Firewall → Options"
    say "    2. LIMA_SSH_PORT_FORWARDER=true: the SSH forwarder cannot do UDP at all"
  else
    say "  nothing in the guest listens yet either — that is the link to close first: run \`bbox run\` again"
    say "  (dgo-net is recreated with the published port, and Lima opens the Mac's socket after it)"
  fi
}

cmd_exec() {
  [ "${1:-}" = "--" ] && shift
  [ $# -gt 0 ] || die "exec needs a command"
  ensure_runtime
  [ "$(state)" = Running ] || cmd_start >&2
  power_agent_start
  # root in the guest, like bbox.cmd's `-u root`: the engine is root's, the drop-in it may rewrite
  # is root's, and the mount maps writes back to the host user regardless of the guest uid.
  # BBOX_IN_GUEST stops bbox from handing itself across a second time. --workdir is this repo,
  # visible in the guest at the same path through the home mount.
  local udp_env; udp_env="$(handoff_env)"
  # `bbox run` is the one hand-off whose RESULT matters to the host, so it runs to completion here
  # (not `exec`) and is followed by the one honest look at the chain. Everything else stays a plain
  # hand-off, with no wrapper between an interactive command and the terminal.
  if [ "${2:-}" = run ]; then
    local rc=0
    guest_shell "$@" || rc=$?
    post_run_udp_note
    return "${rc}"
  fi
  guest_shell "$@"
}

# `sudo -H`, never `sudo -i`: -i re-parses its arguments through a login shell, so every `$var`
# and `$(…)` in the command string was expanded a second time (as empty) before bash -c saw it.
# The two host facts ride along here too — a hand-off is a hand-off, and a `bbox run` typed inside an
# interactive shell must see exactly what bbox itself hands across, or the guest's answer to "can
# this office be dialed" would depend on which door was used.
cmd_shell()  { ensure_runtime; [ "$(state)" = Running ] || cmd_start >&2; local udp_env; udp_env="$(handoff_env)"; exec "${LIMACTL}" shell --workdir "${REPO_ROOT}" "${INSTANCE}" -- sudo -H env BBOX_IN_GUEST=1 HOME=/root ${udp_env} bash -c "cd '${REPO_ROOT}'; ${*:-exec bash}"; }
cmd_stop()   { ensure_runtime; power_agent_stop; case "$(state)" in Running) lima stop "${INSTANCE}"; ok "engine stopped (state kept)";; "") say "engine not created";; *) ok "engine already stopped";; esac; }
cmd_status() { ensure_runtime; local st; st="$(state)"; echo "${st:-not created}"; [ "${st}" = Running ]; }
cmd_socket() { host_socket; }
cmd_destroy() {
  [ "${1:-}" = "--force" ] || die "destroy deletes the guest disk — every image, container and volume of this stack on this Mac. Re-run with --force to confirm."
  ensure_runtime; [ -n "$(state)" ] || { say "engine not created"; return 0; }
  lima delete --force "${INSTANCE}"; ok "engine deleted (${LIMA_HOME}/${INSTANCE})"
}
cmd_doctor() {
  ensure_runtime
  echo "macOS $(sw_vers -productVersion) $(uname -m) · $(sysctl -n hw.ncpu) cores · $(host_mem_gib) GiB"
  echo "lima:      ${LIMACTL} ($(lima --version 2>/dev/null))"
  echo "LIMA_HOME: ${LIMA_HOME}"
  echo "template:  ${TEMPLATE}"
  echo "sizing:    cpus=$(vm_cpus) mem=$(vm_mem)GiB disk=$(vm_disk)GiB  (BBOX_VM_CPUS/BBOX_VM_MEM/BBOX_VM_DISK override)"
  echo "rosetta:   $([ -n "$(rosetta_flags)" ] && echo present || echo absent)"
  echo "state:     $(state || true)"
  echo "socket:    $(host_socket)"
  forward_report
  [ "$(state)" = Running ] && lima shell "${INSTANCE}" sudo docker version --format '  engine:    Docker {{.Server.Version}} (API {{.Server.APIVersion}}, min {{.Server.MinAPIVersion}})' 2>/dev/null || true
}

# ── the pair tunnel's UDP forward: the chain, its three links, and how an older engine gets the rule ─
# engine.yaml is what a NEW engine is created from, and an instance keeps the config it was created
# with — so a Mac whose engine predates the rule has to be edited to match. What is reported is the
# CHAIN (see `udp_listening` above): the instance's rule, whether the guest listens, and whether the
# Mac holds the socket. Each fails on its own, and only the last one, with the middle one up, is a
# fault on this machine — the other states are "not yet", and the report says which step closes them.
forward_report() {
  local lan ports port bound held wanted handoff
  lan="$(lan_addr)"
  ports="$(instance_ports)"
  wanted="$(template_udp_json)"
  printf 'lan:       %s\n' "${lan:-none — this Mac has no default route, so nothing on the network can dial it}"
  if [ -n "${ports}" ]; then
    for port in ${ports}; do
      bound="no"; guest_udp_bound "${port}" && bound="yes"
      held="no";  udp_listening  "${port}" && held="yes"
      printf 'udp:       %s/udp from 0.0.0.0 — instance: declared · guest listening: %s · Mac socket: %s\n' "${port}" "${bound}" "${held}"
      if [ "${bound}" = no ]; then
        printf '           the office has not published it yet: `bbox run` writes DGO_WG_PUBLISH_PORT /\n'
        printf '           DGO_WG_PUBLISH_BIND=0.0.0.0 and dgo-net then listens. Lima opens the Mac socket\n'
        printf '           only after that (a rule is bound at startup only with `static: true`, TCP only)\n'
      elif [ "${held}" = no ]; then
        printf '           the guest listens and the Mac holds nothing — two candidates, in this order:\n'
        printf '             1. macOS incoming-connection consent denied: System Settings → Network → Firewall → Options\n'
        printf '             2. LIMA_SSH_PORT_FORWARDER=true: the SSH forwarder cannot do UDP at all\n'
      fi
    done
  else
    printf 'udp:       none — this engine forwards TCP only, so the guest can only DIAL\n'
    [ -n "${wanted}" ] && [ "${wanted}" != "[]" ] && printf '           the template declares it; apply it to this instance: ./bbox engine forwards --apply\n'
  fi
  handoff="$(guest_udp_handoff)"
  if [ -n "${handoff}" ]; then
    printf 'guest:     BBOX_HOST_LAN_ADDR=%s BBOX_HOST_UDP_PORT=%s → hooks/prepare declares this office dialable\n' "${handoff%% *}" "${handoff##* }"
  else
    printf 'guest:     no handoff — hooks/prepare keeps DGO_WG_DIAL_ONLY=engine-guest\n'
  fi
}

# Applying it to an engine that already exists. `limactl edit` refuses a RUNNING instance, so the
# order is stop → edit → start, and the office is down for the length of a boot. Nothing in this
# stack declares a restart policy, so no container comes back on its own: the same run calls
# `bbox run` afterwards. Run it from the Mac's Terminal, never from inside the office — the guest it
# stops is the one an agent inside that office is running in.
#
# What this converges is the DECLARATION (the instance's lima.yaml) and nothing else. The socket is
# not the target and never a reason to restart: it appears by itself once the office publishes the
# port and something in the guest listens (see the chain above). An office that already declares the
# rule therefore costs nothing here — no stop, no downtime.
cmd_forwards_apply() {
  local declared want_json want_ports
  declared="$(instance_ports)"
  want_json="$(template_udp_json)"
  want_ports="$(printf '%s' "${want_json}" | /usr/bin/python3 -c 'import json,sys; print(" ".join(str(r["guestPort"]) for r in json.load(sys.stdin)))' 2>/dev/null || true)"
  [ -n "${want_ports}" ] || die "engine.yaml declares no UDP port forward — nothing to apply"
  if [ "${declared}" = "${want_ports}" ]; then
    ok "this instance already declares ${want_ports}/udp — nothing to edit (no restart)"
    forward_report
    post_run_udp_note
    return 0
  fi
  say "this STOPS the office and boots it again (a Lima instance can only be edited while stopped)"
  cmd_stop
  lima edit --tty=false "${INSTANCE}" --set ".portForwards += ${want_json}" \
    || die "limactl edit refused — the instance is still stopped; bring it back with: bbox engine start"
  ok "instance config updated: $(instance_ports)"
  cmd_start
  say "bringing the office back up (no service here restarts by itself after a guest reboot)…"
  "${REPO_ROOT}/bbox" run || say "${cy}bbox run reported an issue — run it again from this Terminal${c0}"
  forward_report
  post_run_udp_note
}

cmd_forwards() {
  ensure_runtime
  case "${1:-}" in
    ""|status|--status) forward_report ;;
    apply|--apply)      cmd_forwards_apply ;;
    *) die "usage: bbox engine forwards [status|--apply]" ;;
  esac
}

cmd="${1:-}"; shift || true
case "${cmd}" in
  start)   cmd_start "$@" ;;
  exec)    cmd_exec "$@" ;;
  shell)   cmd_shell "$@" ;;
  stop)    cmd_stop ;;
  status)  cmd_status ;;
  socket)  cmd_socket ;;
  doctor)  cmd_doctor ;;
  forwards) cmd_forwards "$@" ;;
  power)   cmd_power "$@" ;;
  destroy) cmd_destroy "$@" ;;
  ""|-h|--help|help) sed -n '2,17p' "$0" ;;
  *) die "unknown: bbox engine ${cmd}  (start|stop|status|shell|socket|doctor|forwards|power|destroy)" ;;
esac
