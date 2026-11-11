# DGO-1635 — noVNC vs Selkies for every remote screen the office shows

Research item from the product review of Exampleu's office (`bina-261109-vjlwcr`, MEET-28). Read
2026-11-09. Every figure below is either measured on the HP that morning or cited with the URL it
came from; nothing is quoted from a project's own marketing without saying so.

**Recommendation: Selkies — one transport everywhere a person looks at a screen — and keep the
terminal a terminal.** It is the only candidate that is (a) one WebSocket on one origin, so it passes
Traefik + forwardAuth + the console's `/a/<alias>/` frame like every other app; (b) codec-negotiated
(H.264/VP9/AV1, JPEG last), so the same page works on a phone, in the console iframe and on a laptop;
(c) already in the office (bina-claude's desktop, DGO-1074) and already measured here. The migration
below adds no container to any app and removes processes from one.

---

## 1. What the office runs today (measured on the HP, 2026-11-09 16:20–16:45 UTC)

### 1.1 The two screen stacks, side by side

| | **browser42** (the live browser view) | **bina-claude** (the Claude Desktop view) |
|---|---|---|
| server | `Xtigervnc :99` 1.15.0 (X server **and** VNC server in one process) | `selkies` 2.1.0 (pixelflux capture + encode) |
| transport | `websockify` 0.12.0 → `/websockify` | `/api/websockets` (one WS, text verbs + binary frames) |
| client | `novnc` 1.6.0 (`/view/vnc.html?…&resize=remote&quality=6&compression=2`) | Selkies' own web client (WebCodecs) |
| display server | Xvnc (real RandR resize) | `Xvfb :1` + `selkies` |
| containers in the app | 6 (`browser`, `mcp`, `caddy`, `reaper`, `task-runner`, `task-watchdog`) | 2 (`desktop`, CLI) |
| image | `mydgo-browser42-browser` **2.36 GB** | `bina-claude-desktop` **3.81 GB** (includes the Claude app) |
| limits | 1.13 CPU, 1.75 GiB | 3 CPU, 5 GiB |
| RSS, idle | 428–431 MiB (Chromium + the stack) | 179 MiB |
| CPU, idle | container 17.8 % / 49.5 % / 24.0 % over three samples — **includes a `cp -a` of the profile and Chromium's own work**, so not the stream's cost | 2.0 / 2.6 / 2.1 % of a core |
| CPU of the stream processes alone | `Xtigervnc` 1.1 % (RSS 10 MB) + `websockify` 1.2 % (RSS 5 MB) | `selkies` 1.3 % (RSS 4.4 MB) |

### 1.2 What one screen costs to send

* **noVNC/TigerVNC, full-screen update:** the server's own `EncodeManager` log for a
  measurement client on the office screen (**675 × 502** — the size the owner's own viewer had
  resized the desktop to) reports **9 rectangles, 30.2 KB** for the whole screen (Tight: 1 solid,
  1 bitmap-RLE, 3 indexed-RLE, 4 full-colour), then only the changed rectangles per frame. The
  protocol is damage-driven: a still screen costs **0 B**, which is why the office's browser can be
  watched from a phone on a metered connection for hours.
* **Selkies, first frames:** a client that connected to the live session and sent `START_VIDEO`
  received **7 video messages, 29,557 B in 6.5 s** at a still screen (first video 1.15 s after the
  verb). Selkies' default stream settings are gaming-grade, from the settings reference: `--framerate
  60`, `--video-bitrate 8000` (8 Mbps CBR), `--encoder h264enc`, with `--congestion-control true`
  and `--use-paint-over-quality true` to clean a still screen and then stop
  ([docs.selkies.io/latest/settings](https://docs.selkies.io/latest/settings/), read 2026-11-09).
  The office's own desktop narrows this in `apps/bina-claude/docker-compose.yml`:
  `SELKIES_ENCODER=h264enc,jpeg`, `SELKIES_FRAMERATE=30`.

**That difference is the whole decision.** noVNC is a *pixel-diff* protocol for text screens; Selkies
is a *video* protocol for screens that move. An office that watches a browser at breakfast and a
Claude session at noon needs both behaviours from one client, and Selkies is the only one of the two
that has the second (its JPEG encoder is the graceful floor: `--encoder jpeg` is CPU-striped JPEG,
WebSocket-only, and it decodes in a browser without WebCodecs).

### 1.3 Latency on the office's own paths (measured 2026-11-09)

| path | measure | value |
|---|---|---|
| LAN → the edge (this machine) | `curl` total for the console root, 5 runs | **0.3 – 4.3 ms** |
| through vps1 (public HTTPS) | TCP connect 86–147 ms, request total | **556 – 686 ms** (a full console load, SSO included) |
| MacBook ↔ HP link (WireGuard) | `./bbox dgo link status` | **RTT 5.8 ms**, handshake 47 s ago |

The transport's own latency is what is left after those numbers: on the LAN both stacks are
imperceptible; over vps1 the round trip is 85–150 ms before either protocol adds a frame, so what
matters there is *how many round trips* a protocol needs. Both are one WebSocket; neither adds a TURN
exchange (Selkies' WebRTC mode is opt-in and we do not use it — `--mode websockets` is the default).
That is also the reason WebRTC is the wrong lever for this office: a TURN server is a second
container, a second port range on the edge, and it crosses the office's one-door SSO model.

### 1.4 What we measured *and could not* measure (method, honestly)

The idle figures and the byte counts above are direct readings: `docker stats`, `/proc/<pid>/stat`
CPU-second deltas, Xvnc's `EncodeManager` summary, and a WebSocket client of my own (a small RFB/
WebSocket client run inside the container) against Selkies' `START_VIDEO` verb. A **motion**
benchmark (CPU per frame while the screen animates) I did **not** obtain: the office's browser view
is shared with the owner and was live at the time (his viewer had the desktop at 675 × 502), and a
second synthetic client either raced his resize or was refused by Xvnc
("Client does not support desktop size changes"). I chose not to drive the owner's Chromium or add a
display to it. The frame-cost figures below are therefore the codecs' documented cost (x264 on the
CPU; Tight/JPEG in TigerVNC), not a benchmark of this HP, and should be re-measured once a
dedicated screen exists to measure.

## 2. The field, with licence and footprint

| project | licence (read 2026-11-09) | shape | footprint | verdict for us |
|---|---|---|---|---|
| **noVNC 1.6** + **websockify 0.12** + **TigerVNC 1.15** | noVNC core **MPL-2.0** ([LICENSE.txt](https://github.com/novnc/noVNC/blob/master/LICENSE.txt)); websockify **LGPL-3.0** ([COPYING](https://github.com/novnc/websockify/blob/master/COPYING)); TigerVNC **GPL-2.0** ([LICENCE.TXT](https://github.com/TigerVNC/tigervnc/blob/master/LICENCE.TXT)) | X server + VNC + a WS bridge + a JS client; three pieces, three licences | 10 MB + 5 MB RSS; sub-1 % CPU idle; ~0 B/s on a still screen | what browser42 runs. Cheapest on a still screen, weakest on motion (no H.264, no audio, text-only clipboard), and it needs three of our own JS patches (keyboard, clipboard, navigation) because the remote is pixels |
| **Selkies 2.1/2.2** | server and web client **MPL-2.0**; the default build links **libx264/x265 (GPL-2.0)**; an OpenH264 build opts out ([licensing](https://github.com/selkies-project/selkies/blob/main/docs/licensing.md)) | one server: capture + encode + WS + its own client | 4.4 MB RSS, 1.3 % CPU idle; ~30 KB per keyframe; H.264 while the screen moves | **the pick.** Already installed for bina-claude; MPL-2.0 covers everything we ship, and the GPL is libx264, which our images already carry through Debian's ffmpeg |
| **KasmVNC** | **GPL-2.0** ([LICENSE.TXT](https://github.com/kasmtech/KasmVNC/blob/master/LICENSE.TXT)); a TigerVNC fork by Kasm Technologies | VNC server with browser-native JPEG/WebP, seamless clipboard | one process, but its container images are built on a desktop base; linuxserver publishes them | would work without WebCodecs (JPEG/WebP need no secure context — the one real advantage) but it is GPL-2.0 in *our* image and no one else in the office speaks its protocol. Rejected: its only edge over Selkies is a `--encoder jpeg` flag away in Selkies |
| **Apache Guacamole** | **Apache-2.0** ([open-source](https://guacamole.apache.org/open-source/)) | `guacd` + a Java web app; renders server-side into a canvas; speaks VNC/RDP/SSH/telnet | 2 containers minimum (guacd + tomcat), JVM of a few hundred MB | the right answer to "one door to many machines", the wrong answer to "one screen, leanest". Two containers and a JVM for one screen; rejected |
| **xpra / others** | GPL-2.0 (xpra) | HTML5 client of its own | one process, big dependency tree | no browser-native client stack we already trust; rejected without a trial |

## 3. Recommendation

**Selkies, everywhere a person watches a screen; the terminal stays a terminal.**

1. **One transport.** The console frames every app at `/a/<alias>/` through Traefik with forwardAuth.
   Selkies' client derives its own prefix (`getRoutePrefix()`), works inside a frame
   (`SELKIES_FRAME_ANCESTORS`), and needs exactly one WS path — which is what browser42's
   `passthrough` entry already does for `/websockify`. Nothing in the edge changes.
2. **One privileged component fewer.** Xvnc is an X *server* + VNC server inside the browser's
   container (GPL-2.0, `-SecurityTypes None` on loopback, `VNC_PASSWORD` optional and not a gate —
   `apps/browser42/caddy/Caddyfile`). Selkies is a process in the same image; the gate stays the
   gate (`/gate`, DGO-988) and the VNC password question disappears.
3. **Fewest containers: zero added.** `bina-claude` shows the shape: one image, one desktop process,
   one WS. browser42 loses `websockify` + the `novnc` package + `tigervnc-standalone-server` and
   gains `baseimage-selkies`' server — same container count (6), two processes fewer inside.
4. **The one thing noVNC does better, and what we do about it.** A still screen costs nothing over
   Tight, and text on a metered phone link is cheap. Selkies covers it with settings, not with a
   second stack: `--framerate 30`, a bounded `--video-bitrate` (1.5–2.5 Mbps is right for a desktop;
   the browser is seldom a video), `--rate-control-mode crf` where quality beats a fixed rate, and
   `--encoder h264enc,jpeg` so a browser without WebCodecs still gets a picture. That configuration
   is a compose change, not new code.

## 4. Migration plan (fewest moving parts, reversible at every step)

Ordered so that each step is independently shippable and the office never has two screen stacks in
one app.

1. **Fix the configuration of the one that exists (bina-claude).** Pin `SELKIES_FRAMERATE=30`,
   `SELKIES_VIDEO_BITRATE=2500,800-8000`, `SELKIES_ENCODER=h264enc,jpeg` (already), and
   `SELKIES_RATE_CONTROL_MODE=crf` where the picture is a desktop. Measure the stream again from a
   phone on the LAN and through vps1 — this is the measurement item that this note could not close.
   *Proof:* the dashboard's own statistics panel (fps, bitrate, codec) and one screenshot from the
   phone.
2. **Give browser42 the same server, in its own image.** Replace
   `tigervnc-standalone-server`/`websockify`/`novnc` with the Selkies server over the same `Xvfb`
   (or Selkies' own capture of the existing display), keep `start-browser.sh`'s Chromium launch and
   its `BROWSER42_BIND_ALIAS` narrowing, replace the Caddyfile's `/view/*` + `/websockify` pair with
   one `/api/*` (SSE/WS) route behind the same `gate`. Delete `browser42-keyboard.js`,
   `browser-clipboard.js`, `browser-navigation.js` — Selkies has native touch/IME input, a real
   clipboard and file transfer, so the three patches stop existing rather than being ported.
   *Proof:* a hand-off (DGO-1336) from the console, a phone, and one `bbox b42 task` screenshot.
3. **Remote machines.** Nothing to do for `computers`/`terminal` today: they show a *terminal*
   (`terminal.v1` over HTTP, `apps/computers/shell.py`), and a terminal is cheaper than a screen —
   it must not become one. The day a person needs a remote *desktop* (vps1, the Dell, a client's
   PC), it is the same Selkies server on that machine, reached through the office's link, not a
   second client implementation here.
4. **Then remove the old road.** `apps/browser42/Dockerfile.browser` drops `novnc`,
   `websockify`, `tigervnc-standalone-server`, `tigervnc-common`; the Caddyfile keeps `gate` and
   `/handoff/*`; the image loses ~2 packages and one process pair. That is the step that pays the
   "fewest containers" bill: no container was ever added.

**The one open check before step 2** (name it on the item rather than discover it in production):
Selkies' H.264 decode needs a secure context. `console.localhost` and an HTTPS office are secure;
an office opened at a LAN IP over plain HTTP is not (measured 2026-10-31, `apps/bina-claude/README.md`).
On such an office the browser must be served the JPEG encoder (`SELKIES_ENCODER=jpeg`, or
`h264enc,jpeg` with the client stepping down) — verify it on an HTTP LAN address before switching
the browser view, because that is the one place the owner opens the office from a phone at home.

## 5. What would change this recommendation

* If the office ever needs **many protocols at one door** (RDP to clients' Windows machines, SSH
  consoles, VNC to a customer's camera) — Guacamole, Apache-2.0, two containers, and its own auth
  in front of the office's.
* If a browser without WebCodecs must be the *normal* case on a plain-HTTP office rather than the
  fallback — KasmVNC (JPEG/WebP, no secure context, GPL-2.0) or Selkies' JPEG encoder; measure the
  JPEG encoder first, it is a setting.
* If the office's screens were text-only forever (Selenium watchdogs, no person involved) — noVNC's
  damage-driven Tight is the cheapest possible answer and browser42's current stack would be right;
  that is not the office's job.

## Sources (read 2026-11-09)

* Selkies licensing inventory — https://github.com/selkies-project/selkies/blob/main/docs/licensing.md
* Selkies README (MPL-2.0, WebSocket default, WebRTC opt-in) — https://github.com/selkies-project/selkies
* Selkies settings reference (encoder menu, framerate 60, bitrate 8000, jpeg encoder, WebCodecs
  stepping, x264 measurement at 720p60) — https://docs.selkies.io/latest/settings/
* noVNC licence — https://github.com/novnc/noVNC/blob/master/LICENSE.txt
* websockify licence (LGPL-3.0) — https://github.com/novnc/websockify/blob/master/COPYING
* TigerVNC licence (GPL-2.0) — https://github.com/TigerVNC/tigervnc/blob/master/LICENCE.TXT
* KasmVNC licence (GPL-2.0) — https://github.com/kasmtech/KasmVNC/blob/master/LICENSE.TXT
* Apache Guacamole, open source — https://guacamole.apache.org/open-source/
* In-repo prior art and the office's own measurements: `apps/bina-claude/README.md` (DGO-1074,
  2026-10-31: Selkies 2.1.0 on the Mac, x264 on the CPU, ~400 MB, 11 % of a core idle),
  `apps/browser42/Dockerfile.browser` (TigerVNC in one process, the three JS patches),
  `apps/browser42/caddy/Caddyfile` (`/view/*`, `/websockify`, the `gate`), `apps/bina-claude/docker-compose.yml`.
