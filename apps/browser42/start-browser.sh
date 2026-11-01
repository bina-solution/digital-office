#!/usr/bin/env bash
# Boots a single headed stealth Chromium that BOTH the AI agent (over CDP)
# and the human (over noVNC) attach to. One browser, two drivers.
#
# Display + stream: TigerVNC's Xvnc is the X server AND the VNC server in ONE
# process (it replaces the old Xvfb + x11vnc pair). Unlike Xvfb, Xvnc speaks
# RandR/SetDesktopSize, so noVNC's resize=remote makes the virtual desktop track
# the viewer's window 1:1 — crisp, correct density, no stretch-to-fit "zoom"/blur.
set -euo pipefail

SCREEN_W="${SCREEN_WIDTH:-1920}"
SCREEN_H="${SCREEN_HEIGHT:-1080}"
DISPLAY_NUM="${DISPLAY_NUM:-99}"
export DISPLAY=":${DISPLAY_NUM}"
export HOME="${HOME:-/root}"
# Chromium (same user) needs the X authority cookie to open :99. Xvnc launched
# directly (not via the vncserver wrapper) won't set one up for us, so we manage it.
export XAUTHORITY="${HOME}/.Xauthority"

# Debian ships TigerVNC's server as Xtigervnc (with Xvnc as a common alias).
VNC_BIN="$(command -v Xtigervnc || command -v Xvnc || true)"
[ -n "$VNC_BIN" ] || { echo "FATAL: Xtigervnc/Xvnc not found in image" >&2; exit 1; }
VNC_COMM="$(basename "$VNC_BIN")"

# 1. The virtual desktop + VNC server in one. -geometry is only the STARTING size;
#    resize=remote negotiates the real size to match the viewer window at runtime.
#    AcceptSetDesktopSize (client-driven resize) is on by default in TigerVNC.
start_xvnc() {
    # Clean stale locks: `docker restart` reuses the container fs, so a leftover
    # /tmp/.X99-lock from a previous (crashed) server blocks the new one.
    rm -f "/tmp/.X${DISPLAY_NUM}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM}" 2>/dev/null || true

    # X authorization cookie so X clients (Chromium) can open the display.
    : > "$XAUTHORITY"
    local cookie
    cookie="$(mcookie 2>/dev/null || python3 -c 'import os,binascii;print(binascii.hexlify(os.urandom(16)).decode())')"
    xauth -f "$XAUTHORITY" add ":${DISPLAY_NUM}" . "$cookie" >/dev/null 2>&1 || true

    # VNC auth is OPTIONAL (Authentik gates the Traefik edge). Set BROWSER42_VNC_PASSWORD
    # to require a password as an extra factor; empty => SecurityTypes None.
    local sec=(-SecurityTypes None)
    if [ -n "${VNC_PASSWORD:-}" ]; then
        mkdir -p "${HOME}/.vnc"
        printf '%s\n' "$VNC_PASSWORD" | vncpasswd -f > "${HOME}/.vnc/passwd" 2>/dev/null || true
        chmod 600 "${HOME}/.vnc/passwd" 2>/dev/null || true
        sec=(-SecurityTypes VncAuth -PasswordFile "${HOME}/.vnc/passwd")
    fi

    # -localhost binds RFB to loopback only (Caddy/websockify front it). -AlwaysShared
    # lets multiple noVNC viewers attach at once (like the old x11vnc -shared -forever).
    # -SendPrimary=0: on X11, SELECTING text is a clipboard operation (the PRIMARY selection), and
    # TigerVNC forwards it by default — so every drag of the mouse in the shared Chromium arrived at
    # the viewer as a cut-text and, once the viewer bridged the clipboard, silently replaced the
    # owner's clipboard (reported 2026-09-22: "every text I select gets copied to my clipboard").
    # PRIMARY stays inside the session (middle-click paste still works there); only a real copy is
    # sent to the client. The viewer keeps its own copy-intent gate as the second layer.
    "$VNC_BIN" ":${DISPLAY_NUM}" \
        -geometry "${SCREEN_W}x${SCREEN_H}" \
        -depth 24 \
        -rfbport 5900 -localhost \
        -auth "$XAUTHORITY" \
        -desktop browser42 \
        -AlwaysShared \
        -SendPrimary=0 \
        "${sec[@]}" >/tmp/xvnc.log 2>&1 &
}
start_xvnc
# Wait for the X socket before anything tries to draw to it.
for i in $(seq 1 50); do
    [ -e "/tmp/.X11-unix/X${DISPLAY_NUM}" ] && break
    sleep 0.1
done

# 1b. Watchdog — Xvnc (display + stream) is the foundation of the headed browser.
#     If it dies the browser silently breaks (black view / "Failed to connect" / CDP
#     "Chrome failed to start"), and it can't be restarted in isolation (the WM and
#     browser are bound to the dead display). So exit and let Docker
#     (restart: unless-stopped) restart the whole stack cleanly — stale X locks are
#     cleared on the next start (start_xvnc above).
( sleep 15                       # startup grace: let the stack come up first
  while :; do
    if ! ps -eo comm 2>/dev/null | grep -qx "$VNC_COMM"; then
      echo "[watchdog] $VNC_COMM died — killing the browser child for a clean Docker restart" >&2
      # Kill the CHILD (see the cloakserve launch below): SIGKILL to PID 1 from inside its
      # own namespace is ignored by the kernel, so the old `kill -9 1` was a silent no-op.
      pkill -9 -f cloakserve 2>/dev/null || true
      exit 0
    fi
    sleep 5
  done ) &

# 2. Window manager — without it, popups/dialogs misbehave and look bot-like, AND
#    new windows aren't maximized (live view shows a small window with black borders
#    around it). fluxbox can crash; the watchdog above only guards Xvnc, so a dead WM
#    used to go unnoticed. Supervise it here so the WM — and the maximize loop below,
#    which depends on it via wmctrl — stay up for the life of the container.
mkdir -p "${HOME}/.fluxbox"
cat > "${HOME}/.fluxbox/overlay" <<'EOF'
background: none
EOF
# 2a. Silence fbsetbg, which is what actually painted that desktop with dialog boxes.
#     `background: none` in the overlay is NOT enough with the Squared_for_Debian style: fluxbox still
#     runs the style's rootCommand, fbsetbg runs, finds no wallpaper setter in this image (no feh,
#     hsetroot, xsetroot or Esetroot), and pops a MODAL xmessage that nobody dismisses. One per start,
#     and one per fluxbox respawn below — 44 of them had piled up by 2026-09-22, each drawn over the
#     last, which is what the owner saw as a dialog that "keeps popping up all the time".
#     `session.screen0.rootCommand` in init overrides the style, so give it a command that cannot
#     fail. The sweeper is the belt to that braces: any dialog a future style change brings back is
#     reaped within seconds instead of accumulating forever.
grep -q '^session\.screen0\.rootCommand:' "${HOME}/.fluxbox/init" 2>/dev/null \
  || echo 'session.screen0.rootCommand: true' >> "${HOME}/.fluxbox/init"
( while :; do pkill -f 'xmessage.*fbsetbg' 2>/dev/null || true; sleep 5; done ) &
( while :; do fluxbox >/dev/null 2>&1 || true; sleep 1; done ) &

# 2b. Keep the single browser window exactly ON the desktop, by geometry, every cycle.
#
#     Two things made this necessary, both found on 2026-09-23 from the owner's screen ("not full
#     screen, and the top is cut off"):
#       1. The class filter was `xdotool ... --class Chromium-browser`, which matches NOTHING on this
#          build — its WM_CLASS is "chromium (/profile/__default__)", "Chromium". The old maximize
#          loop had therefore been a silent no-op for as long as that class string has been wrong, and
#          the window sat at a stale size and position (measured: y=-50, 1050x760 on a 1408x793
#          desktop — the title bar and tab strip literally above the visible area).
#       2. noVNC runs with resize=remote, so the desktop changes size whenever a viewer connects or
#          resizes. A window that is merely "maximized" keeps its old geometry through such a change.
#          Fitting by explicit geometry each cycle tracks it, and cannot go stale the same way:
#          `wmctrl -lx` prints the real class, and matching it cannot rot with a Chromium rename.
#     Fullscreen (compact/F11) windows are left alone, so the toolbar toggle still wins.
chromium_window_ids() {
    wmctrl -lx 2>/dev/null | awk 'tolower($3) ~ /chrom/ {print $1}'
}

fit_browser_windows() {
    local target id state geom work
    # Fit to the WORK AREA, not the screen: fluxbox keeps a 20px toolbar at the bottom and clamps a
    # window to 1346x710 on a 1346x730 screen. Fitting to the screen therefore never matched what the
    # window could be, so the loop re-applied itself every 2 seconds — which the owner saw as the
    # whole view flickering. Target the work area and the loop is silent unless the size really moved.
    work="$(xprop -root _NET_WORKAREA 2>/dev/null | sed -n 's/.*= *//p' | cut -d, -f1-4 | tr -d ' ')"
    if [ -z "${work}" ]; then
        work="0,0,$(xdotool getdisplaygeometry 2>/dev/null | tr ' ' ',')"
    fi
    case "${work}" in *,*,*,*) ;; *) return 0 ;; esac
    target="$(printf '%s' "${work}" | tr ',' ' ')"
    set -- ${target}
    target="0 0 ${3} ${4}"
    for id in $(chromium_window_ids); do
        state="$(xprop -id "${id}" _NET_WM_STATE 2>/dev/null || true)"
        case "${state}" in *FULLSCREEN*) continue ;; esac      # leave F11 / compact alone
        geom="$(wmctrl -lG 2>/dev/null | awk -v id="${id}" '$1 == id {print $3, $4, $5, $6}')"
        [ "${geom}" = "${target}" ] && continue                # already right: touch nothing
        set -- ${target}
        wmctrl -i -r "${id}" -b remove,maximized_vert,maximized_horz 2>/dev/null || true
        # xdotool, not `wmctrl -e`: -e wants FIVE comma-separated integers and fails silently with four.
        xdotool windowmove "${id}" "$1" "$2" 2>/dev/null || true
        xdotool windowsize "${id}" "$3" "$4" 2>/dev/null || true
    done
}

( while :; do fit_browser_windows; sleep 2; done ) &
case "${PRESENTATION_MODE:-compact}" in
  compact) START_COMPACT=1 ;;
  standard) START_COMPACT=0 ;;
  *) echo "invalid PRESENTATION_MODE: ${PRESENTATION_MODE}" >&2; exit 1 ;;
esac
( while :; do
    for w in $(chromium_window_ids); do
      wmctrl -i -r "$w" -b add,maximized_vert,maximized_horz 2>/dev/null || true
    done
    sleep 2
  done ) &
if [ "$START_COMPACT" = 1 ]; then
  # Once per NEW window id, for the life of the container — not only at boot: a wake from idle
  # sleep (§4k) launches a fresh Chromium with a fresh window, and it must come up compact exactly
  # like the first one did.
  ( seen=""
    while :; do
      w="$(chromium_window_ids | head -1)"
      if [ -n "$w" ] && [ "$w" != "$seen" ]; then
        sleep 1                                  # let the window map before the key lands
        xdotool windowactivate --sync "$w" key --window "$w" F11 2>/dev/null && seen="$w"
      fi
      sleep 2
    done ) &
fi

# 2c. ONE browser window, always. This container is a single shared control surface — one Chromium
#     and one live view — but extra windows do appear: the CDP retry loop leaves its own window
#     behind on every failed launch (2026-09-23: three of them in the owner's taskbar), and a link
#     opened "in a new window" adds another. At BOOT we converge: keep the first Chromium window,
#     close the rest. Safe by construction — every window shares one profile and one cookie jar, so
#     closing one loses no session, and at boot nothing is in progress. Deliberately boot-only: a
#     background janitor would also close a window the owner opened on purpose.
( for _ in $(seq 1 90); do
    [ -n "$(chromium_window_ids | head -1)" ] && break
    sleep 2
  done
  sleep 25                                  # let a retrying launcher settle before looking again
  first=""
  for w in $(chromium_window_ids); do
    if [ -z "$first" ]; then first="$w"; continue; fi
    echo "[converge] closing extra Chromium window ${w}" >&2
    wmctrl -i -c "$w" 2>/dev/null || true
  done ) &

# 4. websockify serves the noVNC static client AND bridges WS->VNC on one port.
#    Target 127.0.0.1 (not "localhost") to avoid an IPv6/IPv4 mismatch with Xvnc's
#    loopback bind.
websockify --web=/usr/share/novnc 6080 127.0.0.1:5900 >/dev/null 2>&1 &

# 4b. Add Browser42's navigation toggle to noVNC's existing toolbar. The control
#     sends F11 over the current RFB connection, so it changes only Chromium's
#     presentation and never reloads the page, iframe, profile, CDP, or websocket.
#     Same mechanism carries the clipboard bridge (4b'): the viewer has no auto-sync of its
#     own (noVNC 1.6 ships the manual panel only), so the owner's Cmd/Ctrl+V is read, pushed
#     to the remote as a cut-text and then forwarded — KasmVNC's "clipboard seamless".
cp /usr/local/share/browser42/browser-navigation.js /usr/share/novnc/app/browser42-navigation.js
cp /usr/local/share/browser42/browser-clipboard.js /usr/share/novnc/app/browser42-clipboard.js
python3 - <<'PY'
import re
from pathlib import Path

path = Path("/usr/share/novnc/vnc.html")
html = path.read_text()

# IDEMPOTENT, AND IT HEALS WHAT EARLIER STARTS BROKE. vnc.html lives in the container's writable
# layer, so "insert once" ran again on every restart and accumulated a copy each time — observed
# 2026-09-22: two navigation buttons and two navigation <script> tags after two starts. A
# duplicated script is not cosmetic: every copy adds its own listeners, so a doubled clipboard
# module pushes the same Cmd+V twice. Strip our previous injections first, then add exactly one.
button = """            <input type="image" alt="Toggle browser navigation" src="app/images/tab.svg"
        id="browser42_navigation_button" class="noVNC_button"
        title="Show or hide browser tabs and address bar">

"""
# A version stamp in the URL: without it the browser keeps serving its cached copy of an injected
# script after a rebuild, so a fix that IS deployed never reaches the viewer. Cheap, and it makes
# "did my change arrive?" a non-question.
def stamped(name):
    path = Path(f"/usr/share/novnc/app/browser42-{name}.js")
    stamp = int(path.stat().st_mtime) if path.exists() else 0
    return f'    <script type="module" src="app/browser42-{name}.js?v={stamp}"></script>\n'

scripts = "".join(stamped(name) for name in ("navigation", "clipboard"))
html = html.replace(button, "")
html = re.sub(r'[ \t]*<script type="module" src="app/browser42-(navigation|clipboard)\.js(\?v=\d+)?"></script>\n', '', html)

marker = "            <!-- Extra manual keys -->"
if marker not in html:
  raise SystemExit("noVNC toolbar marker not found")
if "</head>" not in html:
  raise SystemExit("noVNC vnc.html has no </head>")

html = html.replace(marker, button + marker, 1)
html = html.replace("</head>", scripts + "</head>", 1)
path.write_text(html)
PY

# 4c. Tuned landing page for /view/: auto-connect, AUTO-RESIZE the remote desktop to
#     the window (resize=remote => crisp 1:1, correct page density — NOT the old
#     stretch-to-fit `scale`, which blurred and looked zoomed), and auto-reconnect —
#     so opening the view is a single click. quality=6 (noVNC default) keeps encode
#     CPU low; over a local viewer bandwidth is free, so higher quality just burns
#     cycles. The VNC password is prefilled only when one is set (it is optional;
#     Authentik gates access). (We replace index.html rather than symlink it, so
#     writing here never clobbers vnc.html.)
[ -n "${VNC_PASSWORD:-}" ] && VNC_PW_PARAM="&password=${VNC_PASSWORD}" || VNC_PW_PARAM=""
rm -f /usr/share/novnc/index.html
cat > /usr/share/novnc/index.html <<HTML
<!doctype html><html><head><meta charset="utf-8"><title>Live view</title>
<meta http-equiv="refresh" content="0; url=vnc.html?autoconnect=true&reconnect=true&resize=remote&quality=6&compression=2${VNC_PW_PARAM}">
</head><body style="margin:0;background:#111"></body></html>
HTML

# 4d. Loopback forwarder for internal *.localhost apps. Chrome pins *.localhost to
#     loopback (RFC 6761) and ignores /etc/hosts + --host-resolver-rules for it, so
#     we can't point the name at Traefik directly. Instead we make loopback actually
#     serve it: listen on 127.0.0.1/[::1] :80 and :443 and L4-forward to Traefik,
#     which routes by Host header (e.g. auth.localhost -> Authentik). One forward
#     per port covers every *.localhost app. Pure-stdlib python3 — no extra package.
if [ -n "${LOCAL_PROXY_TARGET:-}" ]; then
    python3 /usr/local/bin/localhost-forward.py "${LOCAL_PROXY_TARGET}" 80 443 &
fi

# 4f. Invisible loopback broker for native Chrome Tab Groups. The extension's
# service worker connects here; no extension or placeholder page is opened.
python3 /usr/local/bin/browser42-broker.py &

# 4g. CDP self-heal watchdog — the definitive fix for "CDP keeps dying".
#     A saturated headed Chrome (ad-heavy tabs on software compositing over Xvnc)
#     can stall its UI thread for minutes; the DevTools socket then answers 502 and
#     every caller dies, and NOTHING used to recover it (the compose healthcheck
#     marks it unhealthy but never restarts). Instead of staying wedged forever,
#     detect a SUSTAINED outage — 6 consecutive failed probes at 10s intervals
#     (60s; transient page-load spikes and the 45s startup grace don't trigger it)
#     — and kill PID 1 for a clean Docker restart. The restart clears every tab
#     (the profile volume keeps logins/cookies), start-browser.sh clears stale
#     singleton locks, the reaper reconnects, and the live view self-heals.
#     Launched before the exec below so it survives as a background supervisor.
( # WAIT FOR THE FIRST SUCCESS BEFORE COUNTING ANYTHING. The old fixed 45s grace was shorter than a
  # cold start on a loaded host (heavy headed Chromium on software compositing), so this watchdog
  # killed a browser that was still coming up: that restart is what turned a slow start into the
  # 2026-09-22 profile wipe. Patience here costs nothing — until CDP has answered once there is
  # nothing to heal. 15 minutes is the backstop, after which failures are counted as before.
  waited=0
  until python3 -c "import urllib.request as u; u.urlopen('http://localhost:9222/json/version/', timeout=5)" 2>/dev/null; do
    sleep 10
    waited=$((waited + 10))
    if [ "$waited" -ge 900 ]; then
      echo "[cdp-watchdog] CDP did not come up within 15min — counting failures from here" >&2
      break
    fi
  done
  fails=0
  while :; do
    # Asleep (§4k) is not an outage: /json/version would LAUNCH Chrome (cloakserve's handler calls
    # get_or_launch), which is exactly what sleep exists to stop. Stand down until it wakes.
    if [ -f /data/.sleeping ]; then fails=0; sleep 10; continue; fi
    # And NO Chrome is not an outage either: this watchdog heals a Chrome that is alive but whose
    # CDP has stopped answering. When cloakserve reports no process (GET / has no launch side
    # effect), there is nothing to heal — the browser is falling asleep, or the reaper's connect
    # is launching it — and a /json/version probe in that state would itself relaunch the Chrome
    # that was just asked to leave (measured 2026-09-30 20:48: marker down, Chrome gone, and this
    # probe, already in flight, brought it back at 41% of a core).
    active=$(python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://localhost:9222/', timeout=5)).get('active', 0))" 2>/dev/null || echo 0)
    if [ "${active:-0}" -eq 0 ]; then fails=0; sleep 10; continue; fi
    if python3 -c "import urllib.request as u; u.urlopen('http://localhost:9222/json/version/', timeout=5)" 2>/dev/null; then
      fails=0
    else
      fails=$((fails + 1))
      echo "[cdp-watchdog] CDP unreachable ($fails/6)" >&2
      if [ "$fails" -ge 6 ]; then
        echo "[cdp-watchdog] sustained CDP outage — killing the browser child for a clean Chrome" >&2
        # Kill the CHILD, not PID 1: SIGKILL to PID 1 from inside its own namespace is
        # IGNORED by the kernel — proven 2026-08-04 when this watchdog logged the restart
        # mid-run but the container's StartedAt never changed and both tasks stayed wedged.
        # Killing the cloakserve child makes PID 1's wait below return -> container exits
        # -> restart: unless-stopped gives a clean Chrome.
        pkill -9 -f cloakserve 2>/dev/null || true
        exit 0
      fi
    fi
    sleep 10
  done ) &

# 4h. PROFILE GUARD — the profile must never be lost.
#
#     (It was numbered 4f until 2026-09-27. Two sections shared that number and two shared 4g —
#     the loopback broker and the CDP watchdog already owned them — because later work was appended
#     without renumbering, which made every "see §4f" in this file and in ai/context point at two
#     different places. New sections take the next FREE number; never reuse one.)
#
#     Why this exists: cloakserve deletes the ENTIRE profile when CDP does not answer in time. On
#     2026-09-22 a cold start hit that path: the Facebook login and every cookie were gone, and there
#     was no backup to restore from. That note used to end "the binary is third-party and
#     digest-pinned, so the deletion cannot be patched out" — it can, and since 2026-09-27 it is:
#     Dockerfile.browser guards that rmtree for the reserved seed, so the delete no longer happens at
#     all. This guard remains as the second line of defence, because a profile can still be lost by a
#     path nobody patched (kill -9 mid-write, a torn volume, a future image bump that drifts the sed).
#     What protects it:
#       * the snapshot lives OUTSIDE the container volume, on the host (data/browser42/ → /data),
#         so it survives a container recreate AND an image rebuild;
#       * the snapshot is only ever replaced by a profile that LOOKS real (a wiped profile has ~0-1
#         cookies) **and** carries MORE cookies than the snapshot already holds — see
#         snapshot_profile: "logged out" is not "wiped", and the 2026-09-27 loss was exactly that
#         blindness (a logged-out profile of 25 cookies overwrote the snapshot every five minutes);
#       * the copy it replaces is kept as SNAPSHOT_DIR.prev, never deleted, so the last good state
#         cannot be destroyed by the act of protecting it;
#       * every boot checks the profile first and restores it when it looks wiped.
#     Cost of a wipe after this: one boot, no re-login.
PROFILE_DIR=/profile/__default__
SNAPSHOT_DIR=/data/profile-snapshot
MIN_COOKIES=3
# Exported because the cookie counter runs in a python subprocess and reads it from the environment —
# a plain shell variable would silently fall back to its default path.
export PROFILE_DIR SNAPSHOT_DIR

cookie_count_in() {
    python3 - "$1" <<'PY' 2>/dev/null || echo 0
import os, shutil, sqlite3, sys, tempfile, time
src = os.path.join(sys.argv[1], "Default/Cookies")
for attempt in range(3):
    try:
        # Copy the WAL and SHM alongside the DB: Chromium keeps the cookie store in WAL mode, and a
        # copy of the main file alone can present ZERO rows while the live data sits in the -wal.
        # That false "wiped" reading is what kept the runtime guard asleep during the 2026-09-23
        # acceptance test, so this is not a detail.
        tmp = tempfile.mkdtemp()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(src + suffix):
                shutil.copy(src + suffix, os.path.join(tmp, "Cookies" + suffix))
        print(sqlite3.connect(os.path.join(tmp, "Cookies")).execute("select count(*) from cookies").fetchone()[0])
        break
    except Exception:
        if attempt == 2:
            print(0)
        else:
            time.sleep(1)
PY
}

# The directory is an ARGUMENT, not the exported PROFILE_DIR: `PROFILE_DIR=x func` leaks the override
# back into this shell for the rest of the script (bash keeps a function's prefix assignments), after
# which every read of the LIVE profile would silently be a read of the snapshot instead.
profile_cookie_count() { cookie_count_in "${PROFILE_DIR}"; }
snapshot_cookie_count() { cookie_count_in "${SNAPSHOT_DIR}"; }

snapshot_dir_is_real() {
    [ -s "$1/Local State" ] || return 1
    [ -s "$1/Default/Cookies" ] || return 1
    return 0
}
snapshot_is_real() { snapshot_dir_is_real "${SNAPSHOT_DIR}"; }

profile_is_real() {
    [ -s "${PROFILE_DIR}/Local State" ] || return 1
    [ -s "${PROFILE_DIR}/Default/Cookies" ] || return 1
    [ "$(profile_cookie_count)" -ge "${MIN_COOKIES}" ] 2>/dev/null || return 1
    return 0
}

snapshot_profile() {
    profile_is_real || { echo "[profile-guard] live profile looks wiped — snapshot NOT replaced" >&2; return 0; }
    # NOT every "real" profile is worth keeping. A profile that is merely LOGGED OUT carries a dozen
    # tracking cookies (facebook: datr/fr/sb/wd — measured 2026-09-27), sails past profile_is_real,
    # and overwrote a snapshot holding a real login within five minutes of it being taken. Cookie
    # count is the cheapest monotone proxy for "how much state is in here": logging in only ADDS
    # cookies and logging out REMOVES them, so a profile with no more of them than the snapshot
    # already holds may not replace it. Erring this way costs nothing — a stale snapshot of a
    # logged-in profile is still a logged-in profile.
    if snapshot_is_real; then
        live="$(profile_cookie_count)"; have="$(snapshot_cookie_count)"
        if [ "${live:-0}" -le "${have:-0}" ] 2>/dev/null; then
            echo "[profile-guard] live profile has no more cookies than the snapshot (${live} <= ${have}) — snapshot NOT replaced" >&2
            return 0
        fi
    fi
    mkdir -p "${SNAPSHOT_DIR}"
    rm -rf "${SNAPSHOT_DIR}.new" && mkdir -p "${SNAPSHOT_DIR}.new"
    cp -a "${PROFILE_DIR}/." "${SNAPSHOT_DIR}.new/" 2>/dev/null || true
    # Keep the copy being replaced (`.old` used to be deleted outright on the next line): the whole
    # point of this block is that nothing here may be the step that loses the only good state.
    rm -rf "${SNAPSHOT_DIR}.prev"
    mv "${SNAPSHOT_DIR}" "${SNAPSHOT_DIR}.prev" 2>/dev/null || true
    mv "${SNAPSHOT_DIR}.new" "${SNAPSHOT_DIR}" 2>/dev/null || true
    echo "[profile-guard] snapshot updated ($(du -sh "${SNAPSHOT_DIR}" 2>/dev/null | cut -f1), cookies=$(profile_cookie_count))" >&2
}

restore_profile_if_wiped() {
    # The copy to restore FROM: the current snapshot, or the generation it replaced when the current
    # one is itself unreadable. Restoring from neither is the one outcome that loses a login.
    local src="${SNAPSHOT_DIR}"
    if ! snapshot_dir_is_real "${src}" && snapshot_dir_is_real "${SNAPSHOT_DIR}.prev"; then
        src="${SNAPSHOT_DIR}.prev"
    fi
    snapshot_dir_is_real "${src}" || return 0
    profile_is_real && return 0
    echo "[profile-guard] profile is missing or wiped — restoring from ${src}" >&2
    rm -rf "${PROFILE_DIR}" && mkdir -p "${PROFILE_DIR}"
    cp -a "${src}/." "${PROFILE_DIR}/" 2>/dev/null || true
    echo "[profile-guard] restored: cookies=$(profile_cookie_count) at $(du -sh "${PROFILE_DIR}" 2>/dev/null | cut -f1)" >&2
}

restore_profile_if_wiped

# 4h-bis. UNDO THE VENDOR'S RECOVERY. cloakserve's failed-launch path no longer DELETES the profile
#     (Dockerfile.browser quarantines it as `<dir>.corrupt-<epoch>`), but the live directory is still
#     replaced by a fresh one — and a fresh profile has a handful of cookies, so `profile_is_real`
#     (>= 3 cookies) accepts it and the good state is never restored. Measured 2026-09-29: after a
#     run of failed launches the live profile was empty while three quarantines held 33 cookies and a
#     live Facebook session, and the office browser stayed signed out with no saved passwords.
#     The quarantine IS the state we had a second ago, so it wins: the richest quarantine is promoted
#     back over a live profile that holds less. Deterministic — no heuristic about which cookie is a
#     "session" cookie, just compare what is there.
promote_richest_quarantine() {
    local best="" best_n=0 n
    # Only the NEWEST THREE quarantines are candidates. "The state we had a second ago" is by
    # definition recent, and every failed launch adds one directory: 242 had accumulated by
    # 2026-09-30 17:05 (each crash-relaunch of the afternoon made one), and counting cookies in all
    # of them — a DB copy and an sqlite open each — held this boot for ~5 minutes at a core on a
    # loaded box before cloakserve was even started. Older quarantines are history, not candidates;
    # pruning them is the owner's call (they are the only copies of whatever they hold).
    for d in $(ls -td /profile/__default__.corrupt-* 2>/dev/null | head -n 3); do
        [ -d "${d}/Default" ] || continue
        n="$(cookie_count_in "${d}")"
        if [ "${n:-0}" -gt "${best_n}" ] 2>/dev/null; then best="${d}"; best_n="${n}"; fi
    done
    [ -n "${best}" ] && [ "${best_n:-0}" -ge 3 ] || return 0
    local live_n; live_n="$(cookie_count_in "${PROFILE_DIR}")"
    if [ "${live_n:-0}" -lt "${best_n}" ]; then
        echo "[profile-guard] live profile holds ${live_n} cookies, quarantine $(basename "${best}") holds ${best_n} — promoting it back" >&2
        rm -rf "${PROFILE_DIR}.replaced" 2>/dev/null || true
        [ -d "${PROFILE_DIR}" ] && mv "${PROFILE_DIR}" "${PROFILE_DIR}.replaced"
        mv "${best}" "${PROFILE_DIR}"
        snapshot_profile
    fi
}
promote_richest_quarantine

# Periodic refresh, so the snapshot tracks real use rather than the state at boot.
( sleep 120; while :; do snapshot_profile; sleep 300; done ) &

# 4i. RUNTIME GUARD — the wipe is not a boot-time event, and this is measured, not assumed.
#     2026-09-23 10:29: /profile/__default__ was recreated with the container's StartedAt unchanged
#     (09-22 17:03) — i.e. cloakserve tore down and relaunched its Chrome child mid-life and rmtree'd
#     the profile on the way, exactly as it does on a cold start. A boot-only check would have missed
#     it. This watcher does both jobs for the life of the container, every 20s:
#       * the moment a profile that was empty becomes real — a fresh login — is snapshotted straight
#         away, so the window in which a wipe could cost that login is seconds, not the 5-minute
#         periodic interval;
#       * a wipe is repaired immediately: restore the snapshot, then drop the Chrome child so PID 1
#         exits and Docker restarts the stack on a profile that is whole again.
#     It cannot fire by accident: it needs a real snapshot to restore FROM, a wipe to be seen TWICE
#     in a row, and it stays quiet for the first 3 minutes of a boot (Chrome writes its profile
#     during startup).
( sleep 180
  last_state=unknown
  wiped_seen=0
  while :; do
    if profile_is_real; then
      if [ "${last_state}" != "real" ]; then
        snapshot_profile                                  # freshly real (a login) or first sight: protect it now
      fi
      last_state=real
      wiped_seen=0
    else
      wiped_seen=$((wiped_seen + 1))
      # TWO consecutive reads, not a transition: the gate must not depend on having seen a healthy
      # profile first (one false read at boot and it would sleep forever), and a single bad read — a
      # lock, a partial copy, Chrome mid-start — is not a wipe.
      if [ "${wiped_seen}" -ge 2 ] && snapshot_is_real; then
        echo "[profile-guard] WIPE DETECTED at runtime — restoring the snapshot and restarting Chrome" >&2
        restore_profile_if_wiped
        pkill -9 -f cloakserve 2>/dev/null || true
        exit 0
      fi
      last_state=wiped
    fi
    sleep 20
  done ) &

# 4e. Clear stale Chrome singleton locks before launch. ⚠️ This is what makes
#     logins/cookies actually survive a restart. On an unclean stop (docker
#     recreate / kill / crash) Chrome leaves SingletonLock/Cookie/Socket behind,
#     pinned to the OLD container's hostname. On the next start the new Chrome
#     sees "profile appears to be in use by another process on another computer",
#     refuses to open the profile, CDP never comes up — and cloakserve's
#     CDP-timeout handler then `rmtree`s the ENTIRE profile to recover, wiping all
#     cookies/logins. Deleting the stale locks lets Chrome reuse the profile, so
#     state persists. Safe: one container ⇒ one Chrome, so any lock here is stale.
#
#     ⚠️ Both halves of that sentence are now historical. cloakserve's startup rmtree is guarded in
#     Dockerfile.browser since 2026-09-27 (the reserved seed is quarantined, not deleted), so a
#     failed launch can no longer cost a login on its own; this lock clearing is still needed
#     because it is what lets Chrome OPEN the profile instead of failing in the first place.
rm -f /profile/*/Singleton* 2>/dev/null || true

# 4e-bis. "Continue where you left off" — the profile-level setting behind --restore-last-session
#     (docker-compose.yml). Both are needed for a wake after idle sleep (§4k) to reopen the tabs the
#     session had: the flag alone restored nothing on 2026-09-30 (two empty new-tab pages) while the
#     profile's `session.restore_on_startup` was unset. Set here, while Chrome is not running (the
#     file is Chrome's and it rewrites it at exit); idempotent.
python3 - <<'PY' 2>/dev/null || true
import json, os
p = "/profile/__default__/Default/Preferences"
if os.path.exists(p):
    d = json.load(open(p))
    if d.setdefault("session", {}).get("restore_on_startup") != 1:
        d["session"]["restore_on_startup"] = 1
        json.dump(d, open(p, "w"))
PY

# 4j. Logins — keep Chrome's password manager and the credential plane in step, in BOTH directions.
#     The store is a SQLite file Chrome holds open, so an outside write is refused while the browser
#     runs. Right HERE is the only moment it is unheld: the profile is settled, Chrome has not
#     started, and this container still has its identity and its network. Running it on every boot is
#     what makes "a password saved in either place is in both" a property rather than a chore — and
#     it is idempotent, so a boot with nothing to move says nothing.
[ -f /logins.py ] && python3 /logins.py run-queued || true

# 4k. IDLE SLEEP — an unused browser costs nothing. Measured 2026-09-30 15:30-16:06: with no agent
#     and no viewer, this container held 75% of a core (the compositor loop of an idle headed
#     Chromium over Xvnc), and every probe RELAUNCHED it after a crash — cloakserve's /json/version
#     handler calls get_or_launch, and the healthcheck probes /json/version — so under load the box
#     spent its afternoon cold-starting a browser nobody used (RestartCount 37). The owner's rule:
#     the browser sleeps after IDLE seconds without use, loses nothing, and the next use continues
#     where it was.
#
#     Sleep = Chrome exits GRACEFULLY (SIGTERM: it writes its session, cookies and logins to the
#     profile on the volume) and nothing relaunches it: the healthcheck reports healthy while
#     /data/.sleeping exists, the CDP watchdog (§4g) stands down, and the reaper (reaper.py) has
#     released its persistent CDP connection. Xvnc, fluxbox, websockify and cloakserve stay
#     (~60 MB, no CPU). Wake = any client connecting to CDP — the Playwright MCP, group-manager,
#     `bbox b42` — makes cloakserve launch Chrome again (its normal path), and
#     --restore-last-session (docker-compose.yml) brings the tabs back; a human opening /view is a
#     websockify connection, seen here and woken the same way. Who decides "idle": the reaper (it
#     sees every tab, every task and the activity markers) writes /data/.sleep-request; this loop
#     decides on its own only when NO client is connected at all, so a dead reaper never means a
#     browser that never sleeps.
#
#     Setting: /data/settings.json {"idle_sleep_s": N} — `bbox b42 sleep after N` — wins over
#     BROWSER42_IDLE_SLEEP_S (.env, default 120); 0 = never. Markers under /data/.activity/:
#     boot (this script), viewer (this loop, while /view is connected), agent (group-manager, every
#     verb). `bbox b42 sleep now|wake|status` are the hands on it.
ACTIVITY_DIR=/data/.activity
SLEEPING=/data/.sleeping
SLEEP_REQUEST=/data/.sleep-request
SETTINGS=/data/settings.json
mkdir -p "${ACTIVITY_DIR}" && touch "${ACTIVITY_DIR}/boot"
rm -f "${SLEEPING}" "${SLEEP_REQUEST}"        # a boot IS a wake: nothing is asleep after a restart

idle_sleep_s() {
    local v
    v="$(python3 -c 'import json,sys; print(int(json.load(open(sys.argv[1])).get("idle_sleep_s")))' "${SETTINGS}" 2>/dev/null || true)"
    printf '%s' "${v:-${BROWSER42_IDLE_SLEEP_S:-120}}"
}
# An ESTABLISHED TCP connection to websockify (:6080) = somebody has /view open.
viewer_connected() {
    python3 - <<'PY'
import sys
for f in ("/proc/net/tcp", "/proc/net/tcp6"):
    try:
        for line in open(f).read().splitlines()[1:]:
            c = line.split()
            if c[3] == "01" and int(c[1].rsplit(":", 1)[1], 16) == 6080:
                sys.exit(0)
    except OSError:
        pass
sys.exit(1)
PY
}
# cloakserve's status endpoint (GET /) reports its Chrome processes and client connections
# WITHOUT launching anything — unlike /json/version. Prints "<active processes> <connections>".
chrome_status() {
    python3 - <<'PY' 2>/dev/null || echo "0 0"
import json, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:9222/", timeout=5))
p = d.get("processes", {}).get("__default__") or {}
print(d.get("active", 0), p.get("connections", 0))
PY
}
last_activity_epoch() {
    local t=0 f m
    for f in "${ACTIVITY_DIR}"/*; do
        [ -e "${f}" ] || continue
        m="$(stat -c %Y "${f}" 2>/dev/null || echo 0)"
        [ "${m}" -gt "${t}" ] && t="${m}"
    done
    echo "${t}"
}
# The browser's main process: the oldest one carrying the shared profile's user-data-dir.
chrome_pid() { pgrep -o -f -- '--user-data-dir=/profile/__default__' 2>/dev/null | head -1; }

# Ask Chrome ITSELF to quit — CDP Browser.close on Chrome's own port, not through cloakserve (whose
# guard rightly refuses Browser.close from clients). A normal shutdown writes the session files and
# leaves exit_type "Normal", which is what lets --restore-last-session reopen the tabs on the next
# launch; a SIGTERM reads to Chromium as a crash (exit_type "Crashed": measured 2026-09-30 20:03)
# and the tabs came back as empty new-tab pages. SIGTERM stays as the fallback.
chrome_close_gracefully() {
    python3 - <<'PY' 2>/dev/null
import asyncio, json, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:9222/", timeout=5))
port = ((d.get("processes") or {}).get("__default__") or {}).get("port")
if not port:
    raise SystemExit(1)
v = json.load(urllib.request.urlopen("http://127.0.0.1:%s/json/version" % port, timeout=5))
from websockets.asyncio.client import connect
async def go():
    async with connect(v["webSocketDebuggerUrl"], max_size=None) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
        try:
            await asyncio.wait_for(ws.recv(), 5)
        except Exception:
            pass
asyncio.run(go())
PY
}

do_sleep() {
    local pid i; pid="$(chrome_pid)"
    if [ -z "${pid}" ]; then rm -f "${SLEEP_REQUEST}"; return 0; fi
    echo "[idle-sleep] idle $(( $(date +%s) - $(last_activity_epoch) ))s — Chrome exits gracefully; the next CDP client or /view session wakes it" >&2
    # The marker goes down FIRST. Measured 2026-09-30 20:01: written after the exit, it left a window
    # of up to 15 s in which the CDP watchdog (§4g) probed /json/version — cloakserve's launch path —
    # and relaunched the Chrome that had just been asked to leave; the sleeper then read "a client
    # launched Chrome" and cleared the marker it had just written. With the marker down before the
    # exit, the watchdog and the healthcheck stand down before there is anything to relaunch.
    date +%s > "${SLEEPING}"
    chrome_close_gracefully || kill -TERM "${pid}" 2>/dev/null || true
    for i in $(seq 1 40); do kill -0 "${pid}" 2>/dev/null || break; sleep 0.5; done
    if kill -0 "${pid}" 2>/dev/null; then
        kill -TERM "${pid}" 2>/dev/null || true
        for i in $(seq 1 20); do kill -0 "${pid}" 2>/dev/null || break; sleep 0.5; done
        kill -0 "${pid}" 2>/dev/null && kill -KILL "${pid}" 2>/dev/null
    fi
    rm -f "${SLEEP_REQUEST}"
    snapshot_profile >/dev/null 2>&1 || true      # a stopped Chrome is the one consistent copy
}
wake_up() {
    echo "[idle-sleep] waking: $1" >&2
    # /json/version IS the launch path (get_or_launch); the marker goes once Chrome answers.
    python3 -c "import urllib.request as u; u.urlopen('http://127.0.0.1:9222/json/version/', timeout=200)" 2>/dev/null || true
}
( sleep 60                                       # boot grace: the reaper connects and Chrome launches first
  was_active=0; zero_since=0
  while :; do
    viewer_connected && touch "${ACTIVITY_DIR}/viewer"
    if [ -f "${SLEEPING}" ]; then
      set -- $(chrome_status)
      if [ "${1:-0}" -ge 1 ]; then
        rm -f "${SLEEPING}"; touch "${ACTIVITY_DIR}/launch"; was_active=1; zero_since=0
        echo "[idle-sleep] awake — a client launched Chrome" >&2
      elif [ "$(last_activity_epoch)" -gt "$(cat "${SLEEPING}" 2>/dev/null || echo 0)" ]; then
        # ONE Chrome only: a launch may already be in flight (a CDP client connected, or `sleep wake`
        # called /json/version) — then a chromium process exists and this loop merely waits for it
        # to answer. Otherwise launch in the BACKGROUND: wake_up blocks for the whole launch, and a
        # blocked loop cannot clear the marker when Chrome comes up (measured 2026-09-30 20:08).
        if [ -z "$(chrome_pid)" ] && [ ! -f /tmp/.b42-waking ]; then
          touch /tmp/.b42-waking
          ( wake_up "activity after sleep"; rm -f /tmp/.b42-waking ) &
        fi
      fi
      sleep 5; continue
    fi
    if [ -f "${SLEEP_REQUEST}" ]; then do_sleep; was_active=0; zero_since=0; sleep 5; continue; fi
    # Own decision, for the case nobody else decides — and only then. Measured 2026-09-30 18:51: a
    # cold launch took 52 s, the reaper's connect gave up at 30 s (zero clients), and this branch put
    # the freshly READY Chrome to sleep ten seconds later because idle was counted from the boot
    # marker. So: a launch IS activity (the 0→1 transition touches a marker), and "nobody connected"
    # must itself have lasted the whole limit — a client that is merely mid-connect does not count
    # as absent.
    limit="$(idle_sleep_s)"
    set -- $(chrome_status)
    if [ "${1:-0}" -ge 1 ] && [ "${was_active}" -eq 0 ]; then touch "${ACTIVITY_DIR}/launch"; was_active=1; zero_since=0; fi
    [ "${1:-0}" -ge 1 ] || was_active=0
    if [ "${2:-0}" -eq 0 ]; then [ "${zero_since}" -eq 0 ] && zero_since=$(date +%s); else zero_since=0; fi
    # The own decision is a FALLBACK for a dead reaper, so it is slow on purpose: at least ten
    # minutes with no client at all. Measured 2026-09-30 20:45-20:50 with the limit applied here as
    # well: on a loaded box the reaper's connect took longer than the limit, this branch slept the
    # browser under it, the reaper's reconnect launched it again, and so on — three cycles in five
    # minutes. The reaper decides the normal case; this branch only catches the case nobody does.
    own_limit="${limit}"; [ "${own_limit:-0}" -lt 600 ] && own_limit=600
    if [ "${limit:-0}" -gt 0 ] 2>/dev/null && [ "${1:-0}" -ge 1 ] && [ "${zero_since}" -gt 0 ]; then
      now=$(date +%s)
      if [ $(( now - zero_since )) -ge "${own_limit}" ] && [ $(( now - $(last_activity_epoch) )) -ge "${own_limit}" ]; then
        do_sleep; was_active=0; zero_since=0
      fi
    fi
    sleep 10
  done ) &

# 5. The stealth browser itself. `cloakserve` launches CloakBrowser's patched
#    Chromium with all 58 fingerprint patches and exposes CDP on :9222.
#    0.0.0.0 lets the sibling MCP container reach CDP over the compose network.
#
#    Rendering to the X display (so the human sees it over noVNC) is the subtle part:
#    - Do NOT pass `--headless=false`. cloakserve forwards that flag to Chromium
#      verbatim, and Chromium 146 treats the mere *presence* of `--headless` as
#      headless-on (the `false` value is ignored) — so it renders offscreen and
#      the live view stays blank.
#    - Instead force `--ozone-platform=x11`. This build's compiled-in default
#      ozone backend is `headless` (offscreen); x11 makes Chromium map a real
#      window onto the Xvnc display :99 — exactly what noVNC streams out.
#    Stealth is unaffected: the fingerprint patches (not `--headless`) hide
#    automation, and the UA already reports real "Chrome", not HeadlessChrome.
#
#    ⚠️ Do NOT `exec` here. PID 1 must stay this script: SIGKILL sent to PID 1 from
#    inside its own namespace is ignored by the kernel, so the watchdogs could never
#    restart the container the old `exec`+`kill -9 1` way (silent no-op). Run cloakserve
#    as a CHILD; watchdogs kill the child, the wait returns, PID 1 exits, and Docker
#    (restart: unless-stopped) brings a clean stack. The trap keeps `docker stop`
#    graceful: forward TERM to the child instead of letting bash swallow it.
#    LAUNCH WAIT. cloakserve gives a launching Chrome 10 s to bind CDP (`_wait_for_cdp(port,
#    timeout=10.0)`) and on a miss kills it, QUARANTINES the profile (Dockerfile.browser's patch —
#    the live directory is moved aside, so the next launch starts from an empty profile) and answers
#    502. A cold headed Chromium with a real profile and --restore-last-session takes 15-40 s on this
#    4-vCPU engine under load — measured 2026-09-30 17:42-17:59: every wake attempt at load 50 missed
#    the 10 s, so each one cost a quarantine and a relaunch (242 `.corrupt-*` directories by 17:05,
#    RestartCount 37). 60 s is the budget a slow box needs; a Chrome that cannot bind in 60 s is
#    genuinely broken. Patched here, at runtime, because the file is plain Python in the writable
#    layer and a Dockerfile patch would sit before the apt layer and force a full image rebuild; the
#    anchor is asserted so a vendor bump that moves the line is heard, not silently unpatched.
if grep -q 'async def _wait_for_cdp(port: int, timeout: float = 10.0)' /usr/local/bin/cloakserve; then
    # 180 s: at load 46 (2026-09-30 21:08) a cold start needed more than 90 and the first attempt
    # was quarantined; a Chrome that cannot bind CDP in three minutes is genuinely broken.
    sed -i 's/async def _wait_for_cdp(port: int, timeout: float = 10.0)/async def _wait_for_cdp(port: int, timeout: float = 180.0)/' /usr/local/bin/cloakserve
elif ! grep -q 'async def _wait_for_cdp(port: int, timeout: float = 180.0)' /usr/local/bin/cloakserve; then
    echo "[start-browser] WARNING: cloakserve's _wait_for_cdp anchor not found — launch wait NOT raised; re-derive the patch" >&2
fi
cloakserve \
    --host=0.0.0.0 \
    --port=9222 \
    --ozone-platform=x11 \
    --data-dir=/profile \
    ${CLOAK_EXTRA_ARGS:-} &
B42_CHILD=$!
# Snapshot the profile AFTER the browser has stopped writing, so the copy is consistent — and the
# last thing this script does before it dies is protect the logins it was serving.
trap 'kill -TERM "${B42_CHILD}" 2>/dev/null; wait "${B42_CHILD}"; snapshot_profile >/dev/null 2>&1; exit 0' TERM INT
wait "${B42_CHILD}"
B42_EXIT=$?
echo "[start-browser] cloakserve exited (${B42_EXIT}) — exiting for a clean Docker restart" >&2
snapshot_profile >/dev/null 2>&1 || true
exit "${B42_EXIT}"
