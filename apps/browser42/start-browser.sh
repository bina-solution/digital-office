#!/usr/bin/env bash
# Boots a single headed stealth Chromium that BOTH the AI agent (over CDP)
# and the human (over noVNC) attach to. One browser, two drivers.
#
# Display + stream: TigerVNC's Xvnc is the X server AND the VNC server in ONE
# process (it replaces the old Xvfb + x11vnc pair). Unlike Xvfb, Xvnc speaks
# RandR/SetDesktopSize, so noVNC's resize=remote makes the virtual desktop track
# the viewer's window 1:1 — crisp, correct density, no stretch-to-fit "zoom"/blur.
#
# What runs here, each in one line (DGO-1921; apps/browser42/README.md has the whole app):
#   Xvnc (display + VNC) · fluxbox (window manager) · websockify (noVNC, the live view) ·
#   localhost-forward (*.localhost → Traefik) · broker (tab groups ↔ the extension) · handoff.py (the
#   gate and the hand-off link) · the internal forwarder (all four to browser42's own network) ·
#   cloakserve (Chromium, CDP) — every helper under `keep`; and four loops: Xvnc watchdog, the window,
#   the CDP watchdog, idle sleep (a fifth, the profile snapshot, is retired: §4h). Every background loop starts with `set +e`:
#   a subshell inherits `set -e`, and one failing probe used to end a loop for good.
set -euo pipefail

# keep NAME COMMAND… — a helper that must run for the life of the container: started now, and started
# again whenever it exits. Every helper is kept the same way; until DGO-1921 three had no supervisor
# and three had a loop of their own.
keep() {
    local name="$1"; shift
    ( set +e
      while :; do
        "$@"
        echo "[keep] ${name} exited ($?) — starting it again" >&2
        sleep 1
      done ) &
}

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
        "${sec[@]}" >&2 &                  # its log is the container's (rotated), not a file in /tmp
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
( set +e
  sleep 15                       # startup grace: let the stack come up first
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

# 2. Window manager — without it, popups/dialogs misbehave and look bot-like, AND new windows aren't
#    maximized (a small window with black borders around it in the live view). Kept like every helper.
#    (Its wallpaper dialog is gone at the root: the image has no fbsetbg to run — Dockerfile.browser.)
run_fluxbox() { fluxbox >/dev/null 2>&1; }
keep fluxbox run_fluxbox

# 2b. THE WINDOW — one loop, every 2 s (DGO-1921: it was four loops and a dialog sweeper, and the
#     compact one ended at boot whenever fluxbox was not up yet — its subshell inherited `set -e`, and
#     wmctrl fails while there is no window manager — so the browser ran maximized, not compact).
#       * A NEW Chromium window is made compact (Chrome's own fullscreen, what F11 toggles) when
#         PRESENTATION_MODE=compact — every launch, a wake from idle sleep included — as a STATE through
#         browser42-window.py, never by pressing F11: a press Chrome swallowed while starting left it
#         standard, and late presses toggled it back (2026-11-17). Asked each cycle until Chrome says it
#         is so, then never again for that window: the viewer's toggle and the hand-off decide after that,
#         and a window the hand-off made standard (STANDARD_MARK) is never made compact again.
#       * A window that is not fullscreen is fitted to the WORK AREA by geometry when it is off, and kept
#         maximized: noVNC's resize=remote changes the desktop whenever a viewer connects, and a merely
#         "maximized" window keeps its old size through that (2026-09-23: y=-50, the tab strip above
#         the screen). The work area, not the screen: fluxbox's toolbar takes 20 px, and fitting to the
#         screen re-applied itself every cycle, which the owner saw as flicker.
#       * Once, 30 s after the first window appears — and only when that is within 5 minutes of boot —
#         extra windows are closed: a launch that failed leaves its window behind (2026-09-23: three in
#         the owner's taskbar), and at boot nothing is in progress. Never again after that: a window the
#         owner or an agent opens on purpose stays.
#     `wmctrl -lx` prints the real class ("chromium (/profile/__default__)"), which cannot rot the way a
#     hard-coded class string did. xdotool moves and sizes: `wmctrl -e` wants five integers.
chromium_window_ids() {
    wmctrl -lx 2>/dev/null | awk 'tolower($3) ~ /chrom/ {print $1}'
}

fit_browser_windows() {
    local area id geom
    area="$(xprop -root _NET_WORKAREA 2>/dev/null | sed -n 's/.*= *//p' | cut -d, -f3-4 | tr -d ' ' | tr ',' ' ')"
    [ -n "${area}" ] || area="$(xdotool getdisplaygeometry 2>/dev/null)"
    set -- ${area}
    [ "$#" -eq 2 ] || return 0
    for id in $(chromium_window_ids); do
        case "$(xprop -id "${id}" _NET_WM_STATE 2>/dev/null)" in *FULLSCREEN*) continue ;; esac
        geom="$(wmctrl -lG 2>/dev/null | awk -v id="${id}" '$1 == id {print $3, $4, $5, $6}')"
        if [ "${geom}" != "0 0 $1 $2" ]; then
            wmctrl -i -r "${id}" -b remove,maximized_vert,maximized_horz 2>/dev/null
            xdotool windowmove "${id}" 0 0 2>/dev/null
            xdotool windowsize "${id}" "$1" "$2" 2>/dev/null
        fi
        wmctrl -i -r "${id}" -b add,maximized_vert,maximized_horz 2>/dev/null
    done
}

case "${PRESENTATION_MODE:-compact}" in
  compact) START_COMPACT=1 ;;
  standard) START_COMPACT=0 ;;
  *) echo "invalid PRESENTATION_MODE: ${PRESENTATION_MODE}" >&2; exit 1 ;;
esac
STANDARD_MARK=/tmp/.b42-standard            # handoff.py writes the window ids it made standard here
( set +e
  booted="$(date +%s)" compacted="" first_seen=0 converged=0
  while :; do
    w="$(chromium_window_ids | head -1)"
    # No Chrome (asleep, restarting): its next window is new, even if X gives it the same id. Asked of
    # the process, not of the window list, which is also empty while fluxbox restarts.
    if [ -z "${w}" ] && ! pgrep -f -- '--user-data-dir=/profile/__default__' >/dev/null; then
      compacted=""; rm -f "${STANDARD_MARK}"
    fi
    if [ "${START_COMPACT}" = 1 ] && [ -n "${w}" ] && [ "${w}" != "${compacted}" ]; then
      if grep -qx "${w}" "${STANDARD_MARK}" 2>/dev/null \
          || timeout 15 python3 /usr/local/bin/browser42-window.py compact 2>/dev/null; then
        compacted="${w}"
      fi
    fi
    fit_browser_windows
    if [ "${converged}" = 0 ] && [ -n "${w}" ]; then
      [ "${first_seen}" -gt 0 ] || first_seen="$(date +%s)"
      [ $(( first_seen - booted )) -le 300 ] || converged=1
      if [ "${converged}" = 0 ] && [ $(( $(date +%s) - first_seen )) -ge 30 ]; then
        for extra in $(chromium_window_ids | tail -n +2); do
          echo "[window] closing extra Chromium window ${extra}" >&2
          wmctrl -i -c "${extra}" 2>/dev/null
        done
        converged=1
      fi
    fi
    sleep 2
  done ) &

# 4a. WHERE THIS CONTAINER LISTENS (DGO-983). It sits on two networks:
#     - browser42's own, where its drivers are (mcp, reaper, watchdog, task runner, caddy);
#     - the office's shared one, for its own calls OUT (Traefik for *.localhost, connections,
#       notifications, any-concurrency).
#     CDP has no credential by design, and the broker and noVNC have none either. Measured
#     2026-10-22: all three answered every container on the shared network, so any of them could
#     read every cookie. Now CDP, the broker, noVNC and the hand-off listen on loopback, and one
#     forwarder (§4f-ter) gives them to browser42's network alone. The address is the one the alias
#     in BROWSER42_BIND_ALIAS resolves to; the alias is declared on browser42's network only.
B42_BIND=""
if [ -n "${BROWSER42_BIND_ALIAS:-}" ]; then
    for _ in {1..30}; do
        B42_BIND="$(python3 -c 'import socket, sys; print(socket.gethostbyname(sys.argv[1]))' "${BROWSER42_BIND_ALIAS}" 2>/dev/null || true)"
        [ -n "${B42_BIND}" ] && break
        sleep 1
    done
    # Refuse rather than fall back to every interface: a browser no driver reaches is a loud
    # failure; one every container reaches is the silent one this exists to remove.
    [ -n "${B42_BIND}" ] || { echo "FATAL: ${BROWSER42_BIND_ALIAS} does not resolve — not serving CDP on every interface" >&2; exit 1; }
    export BROWSER42_BROKER_HOST=127.0.0.1 BROWSER42_HANDOFF_HOST=127.0.0.1 BROWSER42_CDP_HOST=127.0.0.1
    echo "[4a] CDP, broker, noVNC and hand-off on loopback, and on ${B42_BIND} (browser42's network) only"
fi
B42_LOOP="${B42_BIND:+127.0.0.1}"    # loopback when the alias is declared; every interface without it

# 4. websockify serves the noVNC static client AND bridges WS->VNC on one port.
#    Target 127.0.0.1 (not "localhost") to avoid an IPv6/IPv4 mismatch with Xvnc's
#    loopback bind. It is the live view: kept.
run_websockify() { websockify --web=/usr/share/novnc "${B42_LOOP:+${B42_LOOP}:}6080" 127.0.0.1:5900 >/dev/null 2>&1; }
keep websockify run_websockify

# 4b. Add Browser42's navigation toggle to noVNC's existing toolbar. The control
#     sends F11 over the current RFB connection, so it changes only Chromium's
#     presentation and never reloads the page, iframe, profile, CDP, or websocket.
#     Same mechanism carries the clipboard bridge (4b'): the viewer has no auto-sync of its
#     own (noVNC 1.6 ships the manual panel only), so the owner's Cmd/Ctrl+V is read, pushed
#     to the remote as a cut-text and then forwarded — KasmVNC's "clipboard seamless".
#     And the phone keyboard (4b''): on a touch device a TAP on the screen focuses noVNC's
#     keyboard input, because a remote desktop drawn as pixels has no field to focus and the
#     toolbar's own keyboard button sits in a control bar that collapses itself 2s after
#     connect (DGO-575). Touch-only by construction, so the agent's view is unchanged.
#
#     Each module is copied FROM THE IMAGE, so a container recreated from an image older than this
#     code does not carry it. That is said by name and the browser keeps running: it is the office's
#     shared surface, and losing it over a viewer gadget would be the wrong trade — the fix is the
#     rebuild the message names. (The injected <script> tag follows the file: §4b's `stamped` emits
#     nothing for a module that is not there, so a missing one is one line on stderr, not a 404 in
#     every viewer.)
for module in navigation clipboard keyboard; do
  src="/usr/local/share/browser42/browser-${module}.js"
  if [ -f "${src}" ]; then
    cp "${src}" "/usr/share/novnc/app/browser42-${module}.js"
  else
    echo "[4b] ${src} is not in this image — the viewer's ${module} module will not load;" \
         "rebuild it with: ./scripts/dc up -d --build browser42-browser" >&2
  fi
done
# 4b'''. The card over the screen when it does not connect (DGO-437): its stylesheet, beside the navigation module
#     that draws it and loads it by its own URL. An image without it draws no card: the module checks that the
#     sheet loaded, and noVNC's own page stays as it was.
if [ -f /usr/local/share/browser42/browser-card.css ]; then
  cp /usr/local/share/browser42/browser-card.css /usr/share/novnc/app/browser42-card.css
fi
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
    if not path.exists():
        return ""          # a module this image does not carry: no tag, so no 404 in every viewer
    stamp = int(path.stat().st_mtime) if path.exists() else 0
    return f'    <script type="module" src="app/browser42-{name}.js?v={stamp}"></script>\n'

scripts = "".join(stamped(name) for name in ("navigation", "clipboard", "keyboard"))
html = html.replace(button, "")
html = re.sub(r'[ \t]*<script type="module" src="app/browser42-(navigation|clipboard|keyboard)\.js(\?v=\d+)?"></script>\n', '', html)

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
    keep localhost-forward python3 /usr/local/bin/localhost-forward.py "${LOCAL_PROXY_TARGET}" 80 443
fi

# 4f. Invisible loopback broker for native Chrome Tab Groups. The extension's
# service worker connects here; no extension or placeholder page is opened.
keep broker python3 /usr/local/bin/browser42-broker.py

# 4f-bis. The human hand-off route (DGO-571): :8767 behind Caddy's /handoff/* — wake, that group's tab
#     to the front through the broker above, compact → standard, then the live view. It also answers
#     Caddy's gate (`/gate`) before the live view and its websocket (DGO-1336), so it is kept. MOUNTED,
#     not copied (docker-compose.yml), so a fix lands without a rebuild; a container recreated from an
#     older compose has no file and says so — the browser keeps running.
if [ -f /handoff.py ]; then
    keep handoff python3 /handoff.py serve
else
    echo "[4f-bis] /handoff.py is not mounted — /handoff/<slug> will answer 502; recreate: ./scripts/dc up -d browser42-browser" >&2
fi

# 4f-ter. browser42's network alone reaches the four loopback services of §4a: CDP, the broker,
#     noVNC and the hand-off. The same port on browser42's address is piped to loopback, so a
#     driver's URL and the Host header CDP answers with are what they were. It is every driver's only
#     way in, and no health check sees it (they all probe loopback), so it is kept.
if [ -n "${B42_BIND}" ]; then
    keep forwarder env FORWARD_LISTEN="${B42_BIND}" python3 /usr/local/bin/localhost-forward.py 127.0.0.1 9222 8765 6080 8767
fi

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
( set +e
  # WAIT FOR THE FIRST SUCCESS BEFORE COUNTING ANYTHING. The old fixed 45s grace was shorter than a
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

# 4h. (RETIRED 2026-11-24, DGO-2188 — the number is not reused.) THE PROFILE GUARD: until then this script kept
#     a second copy of the whole profile in data/browser42/profile-snapshot — counted the cookies of the
#     profile and of the copy (each count a copy of the cookie store into /tmp), copied the profile every
#     30 minutes, at every sleep and at every stop, rotated three generations, and restored the copy at boot
#     when the profile «looked wiped». It was made for a cloakserve that deleted the profile (2026-09-22,
#     09-27, 09-30), and patch-cloakserve.py removed that at its root on 2026-11-17 (DGO-1921). What the
#     guard itself then did to the office:
#       * 20,383 cookie copies, 25 GB, in /tmp filled the HP's C: to 99% (DGO-1917);
#       * 2.0 GB a copy on C:, 1.9 GB of it cache, and a snapshot frozen for four days by its own rule;
#       * 2026-11-20 09:53Z, the HP's C: answering I/O errors: `rm -rf profile-snapshot.new` failed on
#         dozens of paths, the rotation was left in pieces (the «protected» copy is 12 KB since), Chrome
#         stopped answering beside it, and the office browser stayed down for four days;
#       * every stop waited for a copy before it let the container end.
#     The profile is the app's state and is kept like every app's: in its declared store (app.json `data`),
#     which the office's backup carries. Nothing here copies it, counts it, or puts it back: a copy another
#     generation of this script made (data/browser42/profile-snapshot*, archive/) is left exactly where it
#     is, for a person to use by hand (README.md).

# 4e. Clear stale Chrome singleton locks before launch. ⚠️ This is what makes
#     logins/cookies actually survive a restart. On an unclean stop (docker
#     recreate / kill / crash) Chrome leaves SingletonLock/Cookie/Socket behind,
#     pinned to the OLD container's hostname. On the next start the new Chrome
#     sees "profile appears to be in use by another process on another computer",
#     refuses to open the profile and CDP never comes up. (cloakserve then deleted
#     the profile to recover; patch-cloakserve.py stops that, so what is left is
#     a browser that cannot start.) Safe: one container ⇒ one Chrome, so any lock
#     here is stale.
rm -f /profile/*/Singleton* 2>/dev/null || true

# 4e-bis. Before a launch — at boot here, and after every idle sleep (§4k) — while Chrome is not running
#     (the file is Chrome's, and it rewrites it at exit):
#       * "continue where you left off" (`session.restore_on_startup`), which --restore-last-session
#         needs: the flag alone reopened nothing on 2026-09-30;
#       * the last exit marked clean. With the owner's profile Chrome records every exit as "Crashed",
#         a DevTools Browser.close included (measured 2026-11-17; a fresh profile records "Normal", and no
#         crash dump is written), and then covers the owner's page with "Restore pages? Chromium didn't
#         shut down correctly" at the next start. The reaper reopens the tabs itself (last-tabs.json),
#         so that dialog only stands in the way (DGO-1921).
#     Written to a temporary file, synced and renamed (a half-written Preferences is a reset profile), and
#     never while a Chrome holds the profile (its SingletonLock, taken before it reads the profile).
prepare_profile() {
    python3 - <<'PY' || echo "[profile] Preferences not prepared (above) — the next start may show the restore dialog" >&2
import json, os, sys
p = "/profile/__default__/Default/Preferences"
if not os.path.exists(p):
    sys.exit(0)
d = json.load(open(p, encoding="utf-8"))
d.setdefault("session", {})["restore_on_startup"] = 1
d.setdefault("profile", {}).update({"exit_type": "Normal", "exited_cleanly": True})
tmp = p + ".b42"
with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
    json.dump(d, f)
    f.flush()
    os.fsync(f.fileno())
if os.path.lexists("/profile/__default__/SingletonLock"):
    os.unlink(tmp)                         # a Chrome took the profile meanwhile: its file, not ours
    sys.exit(0)
os.replace(tmp, p)
PY
}
prepare_profile

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
# Running, as opposed to exited: a Chrome that has exited stays a zombie until cloakserve polls it, and
# `kill -0` answers yes for a zombie — so every sleep used to wait its full 20 s and then TERM and KILL a
# process that was already gone (DGO-1921).
pid_running() {
    case "$(sed -n 's/.*) \(.\).*/\1/p' "/proc/$1/stat" 2>/dev/null)" in ''|Z) return 1 ;; *) return 0 ;; esac
}

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
    for i in $(seq 1 40); do pid_running "${pid}" || break; sleep 0.5; done
    if pid_running "${pid}"; then
        kill -TERM "${pid}" 2>/dev/null || true
        for i in $(seq 1 20); do pid_running "${pid}" || break; sleep 0.5; done
        pid_running "${pid}" && kill -KILL "${pid}" 2>/dev/null
    fi
    rm -f "${SLEEP_REQUEST}"
    # The next launch is a wake: prepare as a boot does (§4e-bis) — unless a client has launched one already.
    [ -z "$(chrome_pid)" ] && prepare_profile
    return 0
}
wake_up() {
    echo "[idle-sleep] waking: $1" >&2
    # /json/version IS the launch path (get_or_launch); the marker goes once Chrome answers.
    python3 -c "import urllib.request as u; u.urlopen('http://127.0.0.1:9222/json/version/', timeout=200)" 2>/dev/null || true
}
( set +e
  sleep 60                                       # boot grace: the reaper connects and Chrome launches first
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

# 5. The stealth browser itself. `cloakserve` launches Chromium and exposes CDP on :9222 — on
#    loopback when §4a asked for it (BROWSER42_CDP_HOST), the forwarder giving it to browser42's own
#    network. What this office changes in cloakserve (the profile is never deleted or moved, its
#    launch lock holds, extensions load, Browser.close is refused, a 180 s launch wait, that address,
#    no access log) is all in patch-cloakserve.py, applied when the image is built.
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
cloakserve \
    --host=0.0.0.0 \
    --port=9222 \
    --ozone-platform=x11 \
    --data-dir=/profile \
    ${CLOAK_EXTRA_ARGS:-} &
B42_CHILD=$!
# A stop ends when Chrome has ended, and does nothing else: until DGO-2188 it then copied the whole profile
# (§4h), inside Docker's ten seconds.
trap 'kill -TERM "${B42_CHILD}" 2>/dev/null; wait "${B42_CHILD}"; exit 0' TERM INT
wait "${B42_CHILD}"
B42_EXIT=$?
echo "[start-browser] cloakserve exited (${B42_EXIT}) — exiting for a clean Docker restart" >&2
exit "${B42_EXIT}"
