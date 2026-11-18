#!/bin/sh
# android-emulator's entrypoint (DGO-1797, package 11): the display first (Xvnc on :1, a window manager, websockify
# on 127.0.0.1:6081 — inside the container only), the AVD made once on its volume, then the supervisor, which serves
# the app's screen on :6080 (the tile: the state, start/stop and the live display, its websocket spliced to
# websockify) and starts the emulator only when asked and the heat allows (server/governor.py). Nothing here starts
# the device. Mounted from the checkout (docker-compose.yml), like server/: a change here needs no image build.
set -eu

# a restart keeps the container's files: the last run's display lock would stop Xvnc («already active»)
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
Xvnc :1 -geometry 540x1140 -depth 24 -SecurityTypes None -localhost yes -AlwaysShared -rfbport 5901 &
sleep 1
fluxbox > /dev/null 2>&1 &
# the display's websocket only: the screen (server.py) serves the page and noVNC's files and splices /websockify
# here — a browser never reaches websockify itself (until 2026-11-13 it was the tile: a black desktop when off)
websockify "127.0.0.1:${EMU_VNC_WS_PORT:-6081}" localhost:5901 > /dev/null 2>&1 &

if [ ! -f "/root/.android/avd/${EMU_AVD:-dgo}.ini" ]; then
  echo no | avdmanager create avd -n "${EMU_AVD:-dgo}" \
    -k "system-images;android-35;google_apis;x86_64" -d pixel_6 --force > /dev/null
fi

# The device's hardware, set on EVERY start (an AVD made before this line gets it too): a 720×1600 screen at 320 dpi
# instead of the Pixel 6's 1080×2400 — the GPU is software (swiftshader), so the CPU draws every pixel of every frame,
# and 56% fewer pixels is the largest saving that adds no heat (the owner, 2026-11-13: «still pretty slow»); no
# cameras, which the phone would poll. A changed screen does not match the saved snapshot: that one start is cold.
cfg="/root/.android/avd/${EMU_AVD:-dgo}.avd/config.ini"
if [ -f "${cfg}" ]; then
  [ -z "$(tail -c1 "${cfg}")" ] || printf '\n' >> "${cfg}"   # a key appended never fuses onto a last line
  # the skin too: a device skin (avdmanager's pixel_6) gives the screen its own size and hw.lcd.* would be ignored
  w="${EMU_LCD_WIDTH:-720}"; h="${EMU_LCD_HEIGHT:-1600}"
  for kv in "hw.lcd.width=${w}" "hw.lcd.height=${h}" "hw.lcd.density=${EMU_LCD_DENSITY:-320}" \
            "skin.name=${w}x${h}" "skin.path=_no_skin" "showDeviceFrame=no" \
            "hw.camera.back=none" "hw.camera.front=none"; do
    k="${kv%%=*}"
    if grep -q "^${k}[ ]*=" "${cfg}"; then sed -i "s|^${k}[ ]*=.*|${kv}|" "${cfg}"; else printf '%s\n' "${kv}" >> "${cfg}"; fi
  done
fi

exec python3 /app/server.py
