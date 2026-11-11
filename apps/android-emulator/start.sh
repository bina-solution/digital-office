#!/bin/sh
# android-emulator's entrypoint (DGO-1797, package 11): the display first (Xvnc on :1, a window manager, noVNC on
# :6080 through websockify), the AVD made once on its volume, then the supervisor — which starts the emulator only
# when asked and the heat allows (server/governor.py). Nothing here starts the device.
set -eu

# a restart keeps the container's files: the last run's display lock would stop Xvnc («already active»)
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
Xvnc :1 -geometry 540x1140 -depth 24 -SecurityTypes None -localhost yes -AlwaysShared -rfbport 5901 &
sleep 1
fluxbox > /dev/null 2>&1 &
# the tile opens / — noVNC connected at once, sized to the viewer (browser42's landing page, start-browser.sh).
# Ubuntu's noVNC (1.3) puts `path` at the host's root, so it is computed from the page: inside the console the
# page is /a/android-emulator/ and its socket /a/android-emulator/websockify (the passthrough), on its own host /.
rm -f /usr/share/novnc/index.html
printf '%s\n' '<!doctype html><meta charset="utf-8"><title>Android</title><script>' \
  'var b = location.pathname.replace(/[^/]*$/, "");' \
  'location.replace(b + "vnc.html?autoconnect=true&reconnect=true&resize=scale&quality=6&path=" +' \
  '  encodeURIComponent(b.slice(1) + "websockify"));</script>' \
  > /usr/share/novnc/index.html
websockify --web /usr/share/novnc 6080 localhost:5901 > /dev/null 2>&1 &

if [ ! -f "/root/.android/avd/${EMU_AVD:-dgo}.ini" ]; then
  echo no | avdmanager create avd -n "${EMU_AVD:-dgo}" \
    -k "system-images;android-35;google_apis;x86_64" -d pixel_6 --force > /dev/null
fi

exec python3 /app/server.py
